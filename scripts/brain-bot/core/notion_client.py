"""Async Notion API wrapper with rate limiting and retry."""
import asyncio
import logging
import time
from typing import Any

from notion_client import AsyncClient
from notion_client.errors import APIResponseError

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket rate limiter for Notion API (3 req/s default)."""

    def __init__(self, rate: float = 3.0):
        self.rate = rate
        self.max_tokens = rate
        self.tokens = rate
        self.last_refill = time.monotonic()

    async def acquire(self):
        """Acquire a token, sleeping if necessary until one is available."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens < 1:
            wait = (1 - self.tokens) / self.rate
            await asyncio.sleep(wait)
            self.tokens = 0
            self.last_refill = time.monotonic()
        else:
            self.tokens -= 1


class NotionClientWrapper:
    """Async Notion API client with rate limiting and automatic retry."""

    def __init__(self, token: str, rate_limit: float = 3.0, max_retries: int = 3):
        self._client = AsyncClient(auth=token)
        self._limiter = RateLimiter(rate_limit)
        self._max_retries = max_retries

    async def _request(self, method, *args, **kwargs) -> Any:
        """Execute an API call with rate limiting and exponential-backoff retry."""
        last_exc = None
        for attempt in range(self._max_retries + 1):
            await self._limiter.acquire()
            try:
                return await method(*args, **kwargs)
            except APIResponseError as exc:
                last_exc = exc
                if exc.status in (429,) or exc.status >= 500:
                    if attempt < self._max_retries:
                        backoff = 2 ** attempt
                        logger.warning(
                            "Notion API error %s (attempt %d/%d), retrying in %ds: %s",
                            exc.status,
                            attempt + 1,
                            self._max_retries,
                            backoff,
                            exc.message,
                        )
                        await asyncio.sleep(backoff)
                        continue
                raise
        raise last_exc

    async def query_database(
        self,
        database_id: str,
        filter: dict = None,
        sorts: list = None,
    ) -> list[dict]:
        """Query a Notion database with automatic pagination.

        Strips the ``collection://`` prefix from database_id if present.
        """
        database_id = database_id.replace("collection://", "")
        all_results: list[dict] = []
        cursor = None

        while True:
            kwargs: dict[str, Any] = {
                "database_id": database_id,
                "page_size": 100,
            }
            if filter is not None:
                kwargs["filter"] = filter
            if sorts is not None:
                kwargs["sorts"] = sorts
            if cursor is not None:
                kwargs["start_cursor"] = cursor

            response = await self._request(
                self._client.data_sources.query,
                data_source_id=kwargs.pop("database_id"),
                **kwargs,
            )
            all_results.extend(response["results"])

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return all_results

    async def get_page(self, page_id: str) -> dict:
        """Retrieve a single Notion page by ID."""
        page_id = page_id.replace("collection://", "")
        return await self._request(self._client.pages.retrieve, page_id=page_id)

    async def create_page(
        self,
        parent: dict,
        properties: dict,
        children: list = None,
    ) -> dict:
        """Create a new Notion page."""
        kwargs: dict[str, Any] = {
            "parent": parent,
            "properties": properties,
        }
        if children is not None:
            kwargs["children"] = children
        return await self._request(self._client.pages.create, **kwargs)

    async def update_page(self, page_id: str, properties: dict) -> dict:
        """Update properties on an existing Notion page."""
        page_id = page_id.replace("collection://", "")
        return await self._request(
            self._client.pages.update,
            page_id=page_id,
            properties=properties,
        )

    async def search(self, query: str, filter_type: str = None) -> list[dict]:
        """Search across the Notion workspace.

        Args:
            query: Search text.
            filter_type: Optional object type filter (``"page"`` or ``"database"``).
        """
        kwargs: dict[str, Any] = {"query": query}
        if filter_type is not None:
            kwargs["filter"] = {"value": filter_type, "property": "object"}
        response = await self._request(self._client.search, **kwargs)
        return response["results"]

    async def close(self):
        """Shut down the underlying HTTP client."""
        await self._client.aclose()

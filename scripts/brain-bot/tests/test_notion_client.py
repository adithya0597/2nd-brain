"""Tests for core/notion_client.py — rate limiter and API wrapper."""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

# Create proper notion_client mock with real exception
class _FakeAPIResponseError(Exception):
    def __init__(self, message="", status=400, code="", body=""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body = body

_notion_mock = MagicMock()
_notion_errors_mock = MagicMock()
_notion_errors_mock.APIResponseError = _FakeAPIResponseError
sys.modules.setdefault("notion_client", _notion_mock)
sys.modules.setdefault("notion_client.errors", _notion_errors_mock)

# Patch AsyncClient before import
_notion_mock.AsyncClient = MagicMock

from core.notion_client import RateLimiter, NotionClientWrapper


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_under_limit(self):
        limiter = RateLimiter(rate=10.0)
        # Should not block
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5  # Should be near-instant

    @pytest.mark.asyncio
    async def test_acquire_multiple(self):
        limiter = RateLimiter(rate=100.0)
        # Acquire many tokens quickly
        for _ in range(5):
            await limiter.acquire()
        # Should still be fast with high rate
        assert limiter.tokens >= 0

    @pytest.mark.asyncio
    async def test_token_refill(self):
        limiter = RateLimiter(rate=1000.0)
        # Drain tokens
        limiter.tokens = 0
        limiter.last_refill = time.monotonic() - 1.0  # 1 sec ago
        await limiter.acquire()
        # After refill, should have acquired


# ---------------------------------------------------------------------------
# NotionClientWrapper
# ---------------------------------------------------------------------------

class TestNotionClientWrapper:
    def _make_wrapper(self):
        wrapper = NotionClientWrapper.__new__(NotionClientWrapper)
        wrapper._client = MagicMock()
        wrapper._limiter = MagicMock()
        wrapper._limiter.acquire = AsyncMock()
        wrapper._max_retries = 3
        return wrapper

    @pytest.mark.asyncio
    async def test_request_success(self):
        wrapper = self._make_wrapper()
        mock_method = AsyncMock(return_value={"ok": True})
        result = await wrapper._request(mock_method)
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_request_generic_exception_propagates(self):
        wrapper = self._make_wrapper()
        mock_method = AsyncMock(side_effect=RuntimeError("network error"))

        with pytest.raises(RuntimeError, match="network error"):
            await wrapper._request(mock_method)

    @pytest.mark.asyncio
    async def test_query_database_single_page(self):
        wrapper = self._make_wrapper()
        response = {"results": [{"id": "p1"}], "has_more": False}
        wrapper._request = AsyncMock(return_value=response)

        results = await wrapper.query_database("collection://db-123")
        assert len(results) == 1
        assert results[0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_query_database_pagination(self):
        wrapper = self._make_wrapper()
        page1 = {"results": [{"id": "p1"}], "has_more": True, "next_cursor": "cursor1"}
        page2 = {"results": [{"id": "p2"}], "has_more": False}
        wrapper._request = AsyncMock(side_effect=[page1, page2])

        results = await wrapper.query_database("db-123")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_database_with_filter(self):
        wrapper = self._make_wrapper()
        response = {"results": [], "has_more": False}
        wrapper._request = AsyncMock(return_value=response)

        results = await wrapper.query_database(
            "db-123",
            filter={"property": "Status", "status": {"equals": "Active"}},
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_get_page(self):
        wrapper = self._make_wrapper()
        wrapper._request = AsyncMock(return_value={"id": "page-1", "properties": {}})

        result = await wrapper.get_page("collection://page-1")
        assert result["id"] == "page-1"

    @pytest.mark.asyncio
    async def test_create_page(self):
        wrapper = self._make_wrapper()
        wrapper._request = AsyncMock(return_value={"id": "new-page"})

        result = await wrapper.create_page(
            parent={"database_id": "db-1"},
            properties={"Name": {"title": [{"text": {"content": "Test"}}]}},
        )
        assert result["id"] == "new-page"

    @pytest.mark.asyncio
    async def test_create_page_with_children(self):
        wrapper = self._make_wrapper()
        wrapper._request = AsyncMock(return_value={"id": "new-page"})

        result = await wrapper.create_page(
            parent={"database_id": "db-1"},
            properties={},
            children=[{"type": "paragraph", "paragraph": {"text": "Hello"}}],
        )
        assert result["id"] == "new-page"

    @pytest.mark.asyncio
    async def test_update_page(self):
        wrapper = self._make_wrapper()
        wrapper._request = AsyncMock(return_value={"id": "page-1"})

        result = await wrapper.update_page("collection://page-1", {"Status": {"status": {"name": "Done"}}})
        assert result["id"] == "page-1"

    @pytest.mark.asyncio
    async def test_search(self):
        wrapper = self._make_wrapper()
        wrapper._request = AsyncMock(return_value={"results": [{"id": "s1"}]})

        results = await wrapper.search("test query")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_with_filter(self):
        wrapper = self._make_wrapper()
        wrapper._request = AsyncMock(return_value={"results": []})

        results = await wrapper.search("test", filter_type="page")
        assert results == []

    @pytest.mark.asyncio
    async def test_close(self):
        wrapper = self._make_wrapper()
        wrapper._client.aclose = AsyncMock()

        await wrapper.close()
        wrapper._client.aclose.assert_awaited_once()

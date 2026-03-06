"""API token usage logger — records token counts to SQLite for cost monitoring."""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-model pricing (USD per 1M tokens)
_PRICING = {
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_creation": 1.00,
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "_default": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
}


def _estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_create: int = 0,
) -> float:
    """Estimate USD cost from token counts."""
    prices = _PRICING.get(model, _PRICING["_default"])
    cost = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_read * prices["cache_read"]
        + cache_create * prices["cache_creation"]
    ) / 1_000_000
    return round(cost, 6)


def log_token_usage(
    response,
    caller: str,
    model: str,
    db_path: Path | str | None = None,
) -> dict:
    """Extract token usage from an Anthropic response and log to SQLite.

    Args:
        response: Anthropic API response with `.usage` attribute
        caller: Identifier for the calling code path (e.g. "classifier_tier3", "command_today")
        model: Model name used for the API call
        db_path: Path to SQLite database. If None, uses config.DB_PATH.

    Returns:
        Dict with token counts and cost estimate, or empty dict on failure.
    """
    try:
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0

        cost = _estimate_cost(model, input_tokens, output_tokens, cache_read, cache_create)

        if db_path is None:
            from config import DB_PATH
            db_path = DB_PATH

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """INSERT INTO api_token_logs
                   (caller, model, input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens, cost_estimate_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (caller, model, input_tokens, output_tokens, cache_read, cache_create, cost),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_create,
            "cost_estimate_usd": cost,
        }
    except Exception:
        logger.debug("Token logging failed", exc_info=True)
        return {}

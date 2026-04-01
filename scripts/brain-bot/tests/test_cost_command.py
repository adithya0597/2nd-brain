"""Tests for /brain-cost command -- DB query, formatter, and handler."""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Mock config and telegram before importing modules (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.db_ops import get_cost_summary
from core.formatter import format_cost_report


# ---------------------------------------------------------------------------
# Helper: seed api_token_logs
# ---------------------------------------------------------------------------

def _seed_token_logs(db_path, rows):
    """Insert test rows into api_token_logs.

    Each row: (caller, model, input_tokens, output_tokens, cost_estimate_usd, created_at)
    """
    conn = sqlite3.connect(str(db_path))
    conn.executemany(
        "INSERT INTO api_token_logs (caller, model, input_tokens, output_tokens, "
        "cache_read_tokens, cache_creation_tokens, cost_estimate_usd, created_at) "
        "VALUES (?, ?, ?, ?, 0, 0, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# get_cost_summary tests
# ---------------------------------------------------------------------------

class TestGetCostSummary:

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_lists(self, test_db):
        result = await get_cost_summary(days=30, db_path=test_db)
        assert result == {"daily": [], "by_caller": [], "by_model": []}

    @pytest.mark.asyncio
    async def test_with_data_returns_correct_aggregations(self, test_db):
        _seed_token_logs(test_db, [
            ("command_today", "claude-sonnet-4-5-20250929", 1000, 500, 0.0105, "2026-03-06 10:00:00"),
            ("command_today", "claude-sonnet-4-5-20250929", 2000, 800, 0.0210, "2026-03-06 11:00:00"),
            ("classifier", "claude-haiku-4-5-20251001", 500, 200, 0.0028, "2026-03-06 12:00:00"),
        ])

        result = await get_cost_summary(days=30, db_path=test_db)

        # Daily: all same date, should be 1 row
        assert len(result["daily"]) == 1
        assert result["daily"][0]["calls"] == 3
        assert result["daily"][0]["daily_cost"] == pytest.approx(0.0343, abs=1e-4)

        # By caller: 2 unique callers
        assert len(result["by_caller"]) == 2

        # By model: 2 unique models
        assert len(result["by_model"]) == 2

    @pytest.mark.asyncio
    async def test_days_filtering(self, test_db):
        _seed_token_logs(test_db, [
            ("recent", "claude-sonnet-4-5-20250929", 100, 50, 0.01, "2026-03-06 10:00:00"),
            ("old", "claude-sonnet-4-5-20250929", 100, 50, 0.01, "2025-01-01 10:00:00"),
        ])

        result = await get_cost_summary(days=7, db_path=test_db)

        # Only the recent row should appear (the old one is > 7 days ago)
        callers = [r["caller"] for r in result["by_caller"]]
        assert "old" not in callers

    @pytest.mark.asyncio
    async def test_groups_by_caller_correctly(self, test_db):
        _seed_token_logs(test_db, [
            ("command_today", "claude-sonnet-4-5-20250929", 1000, 500, 0.01, "2026-03-06 10:00:00"),
            ("command_today", "claude-sonnet-4-5-20250929", 2000, 800, 0.02, "2026-03-06 11:00:00"),
            ("classifier", "claude-haiku-4-5-20251001", 500, 200, 0.003, "2026-03-06 12:00:00"),
        ])

        result = await get_cost_summary(days=30, db_path=test_db)
        caller_map = {r["caller"]: r for r in result["by_caller"]}

        assert "command_today" in caller_map
        assert caller_map["command_today"]["calls"] == 2
        assert caller_map["command_today"]["total_cost"] == pytest.approx(0.03, abs=1e-4)

        assert "classifier" in caller_map
        assert caller_map["classifier"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_groups_by_model_correctly(self, test_db):
        _seed_token_logs(test_db, [
            ("a", "claude-sonnet-4-5-20250929", 1000, 500, 0.0105, "2026-03-06 10:00:00"),
            ("b", "claude-sonnet-4-5-20250929", 2000, 800, 0.0210, "2026-03-06 11:00:00"),
            ("c", "claude-haiku-4-5-20251001", 500, 200, 0.0028, "2026-03-06 12:00:00"),
        ])

        result = await get_cost_summary(days=30, db_path=test_db)
        model_map = {r["model"]: r for r in result["by_model"]}

        assert "claude-sonnet-4-5-20250929" in model_map
        assert model_map["claude-sonnet-4-5-20250929"]["calls"] == 2
        assert model_map["claude-sonnet-4-5-20250929"]["total_cost"] == pytest.approx(0.0315, abs=1e-4)

        assert "claude-haiku-4-5-20251001" in model_map
        assert model_map["claude-haiku-4-5-20251001"]["calls"] == 1


# ---------------------------------------------------------------------------
# format_cost_report tests
# ---------------------------------------------------------------------------

class TestFormatCostReport:

    def test_returns_valid_html_tuple(self):
        data = {
            "daily": [
                {"date": "2026-03-06", "calls": 5, "daily_cost": 0.05, "input_tokens": 5000, "output_tokens": 2000},
            ],
            "by_caller": [
                {"caller": "command_today", "calls": 3, "total_cost": 0.03, "avg_input": 1000, "avg_output": 500},
            ],
            "by_model": [
                {"model": "claude-sonnet-4-5-20250929", "calls": 5, "total_cost": 0.05},
            ],
        }

        html, keyboard = format_cost_report(data, days=30)

        assert isinstance(html, str)
        assert keyboard is None
        assert "30" in html
        assert "<b>" in html  # HTML formatting present

    def test_handles_empty_data_gracefully(self):
        data = {"daily": [], "by_caller": [], "by_model": []}

        html, keyboard = format_cost_report(data, days=7)

        assert isinstance(html, str)
        assert "7" in html
        assert "No API calls" in html

    def test_summary_stats_correct(self):
        data = {
            "daily": [
                {"date": "2026-03-06", "calls": 3, "daily_cost": 0.03, "input_tokens": 3000, "output_tokens": 1000},
                {"date": "2026-03-05", "calls": 2, "daily_cost": 0.02, "input_tokens": 2000, "output_tokens": 800},
            ],
            "by_caller": [],
            "by_model": [],
        }

        html, keyboard = format_cost_report(data, days=30)

        assert "$0.0500" in html
        assert "5" in html  # total calls


# ---------------------------------------------------------------------------
# Handler parsing test
# ---------------------------------------------------------------------------

class TestCostCommandHandler:

    def test_handler_has_telegram_signature(self):
        """Verify the handler accepts Telegram (update, context) args."""
        from handlers.commands import _handle_cost

        import inspect
        sig = inspect.signature(_handle_cost)
        params = list(sig.parameters.keys())
        assert params == ["update", "context"]

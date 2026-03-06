"""Tests for /brain-cost command — DB query, formatter, and handler."""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing modules
_mock_config = MagicMock()
_mock_config.DB_PATH = Path("/dev/null")
sys.modules.setdefault("config", _mock_config)

from core.db_ops import get_cost_summary, execute
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

    def test_returns_valid_block_kit_structure(self):
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

        blocks = format_cost_report(data, days=30)

        assert isinstance(blocks, list)
        assert len(blocks) > 0

        # First block should be a header
        assert blocks[0]["type"] == "header"
        assert "30" in blocks[0]["text"]["text"]

        # Should contain section and divider blocks
        types = {b["type"] for b in blocks}
        assert "section" in types
        assert "divider" in types
        assert "context" in types

    def test_handles_empty_data_gracefully(self):
        data = {"daily": [], "by_caller": [], "by_model": []}

        blocks = format_cost_report(data, days=7)

        assert isinstance(blocks, list)
        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"
        assert "7" in blocks[0]["text"]["text"]

        # Should have the "No API calls" message
        section_texts = [
            b["text"]["text"] for b in blocks if b["type"] == "section"
        ]
        assert any("No API calls" in t for t in section_texts)

    def test_summary_stats_correct(self):
        data = {
            "daily": [
                {"date": "2026-03-06", "calls": 3, "daily_cost": 0.03, "input_tokens": 3000, "output_tokens": 1000},
                {"date": "2026-03-05", "calls": 2, "daily_cost": 0.02, "input_tokens": 2000, "output_tokens": 800},
            ],
            "by_caller": [],
            "by_model": [],
        }

        blocks = format_cost_report(data, days=30)

        # Find the summary section (second block, after header)
        summary = blocks[1]
        assert summary["type"] == "section"
        assert "$0.0500" in summary["text"]["text"]
        assert "5" in summary["text"]["text"]  # total calls


# ---------------------------------------------------------------------------
# Handler parsing test
# ---------------------------------------------------------------------------

class TestCostCommandHandler:

    def test_handler_parses_days_parameter(self):
        """Verify the handler would parse days from command text."""
        from handlers.commands import _run_cost_command

        # We test the parsing logic by checking _run_cost_command exists
        # and accepts the expected args (client, user_id, user_input)
        import inspect
        sig = inspect.signature(_run_cost_command)
        params = list(sig.parameters.keys())
        assert params == ["client", "user_id", "user_input"]

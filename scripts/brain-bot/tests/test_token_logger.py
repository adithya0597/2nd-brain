"""Tests for core.token_logger — API token usage logging."""
import sqlite3
from unittest.mock import MagicMock

import pytest

from core.token_logger import _estimate_cost, log_token_usage


# ---------------------------------------------------------------------------
# _estimate_cost tests
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_haiku_pricing(self):
        cost = _estimate_cost(
            model="claude-haiku-4-5-20251001",
            input_tokens=1000,
            output_tokens=500,
        )
        # 1000 * 0.80 / 1M + 500 * 4.00 / 1M = 0.0008 + 0.002 = 0.0028
        assert cost == pytest.approx(0.0028, abs=1e-6)

    def test_sonnet_pricing(self):
        cost = _estimate_cost(
            model="claude-sonnet-4-5-20250929",
            input_tokens=1000,
            output_tokens=500,
        )
        # 1000 * 3.00 / 1M + 500 * 15.00 / 1M = 0.003 + 0.0075 = 0.0105
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_unknown_model_uses_default(self):
        cost = _estimate_cost(
            model="some-future-model",
            input_tokens=1000,
            output_tokens=500,
        )
        # Default pricing matches Sonnet
        expected = _estimate_cost("claude-sonnet-4-5-20250929", 1000, 500)
        assert cost == expected

    def test_with_cache_tokens(self):
        cost = _estimate_cost(
            model="claude-haiku-4-5-20251001",
            input_tokens=1000,
            output_tokens=500,
            cache_read=200,
            cache_create=100,
        )
        # base: 0.0028 (from test above)
        # + 200 * 0.08 / 1M = 0.000016
        # + 100 * 1.00 / 1M = 0.0001
        expected = 0.0028 + 0.000016 + 0.0001
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_zero_tokens(self):
        cost = _estimate_cost(
            model="claude-haiku-4-5-20251001",
            input_tokens=0,
            output_tokens=0,
        )
        assert cost == 0.0


# ---------------------------------------------------------------------------
# log_token_usage tests
# ---------------------------------------------------------------------------


def _mock_response(input_tokens=100, output_tokens=50, cache_read=20, cache_create=10):
    """Create a mock Anthropic response with usage attributes."""
    response = MagicMock()
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    response.usage.cache_read_input_tokens = cache_read
    response.usage.cache_creation_input_tokens = cache_create
    return response


class TestLogTokenUsage:
    def test_inserts_row_into_db(self, test_db):
        response = _mock_response()
        log_token_usage(
            response,
            caller="test_caller",
            model="claude-haiku-4-5-20251001",
            db_path=test_db,
        )

        conn = sqlite3.connect(str(test_db))
        rows = conn.execute("SELECT * FROM api_token_logs").fetchall()
        conn.close()
        assert len(rows) == 1
        # Check caller and model
        assert rows[0][1] == "test_caller"
        assert rows[0][2] == "claude-haiku-4-5-20251001"

    def test_returns_correct_dict(self, test_db):
        response = _mock_response(input_tokens=100, output_tokens=50, cache_read=20, cache_create=10)
        result = log_token_usage(
            response,
            caller="test_caller",
            model="claude-haiku-4-5-20251001",
            db_path=test_db,
        )

        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cache_read_tokens"] == 20
        assert result["cache_creation_tokens"] == 10
        assert "cost_estimate_usd" in result
        assert result["cost_estimate_usd"] > 0

    def test_handles_missing_usage_attribute(self, test_db):
        response = MagicMock(spec=[])  # No attributes at all
        result = log_token_usage(
            response,
            caller="test_caller",
            model="claude-haiku-4-5-20251001",
            db_path=test_db,
        )
        assert result == {}

    def test_handles_db_error(self, tmp_path):
        response = _mock_response()
        # Point to a non-existent directory so sqlite3.connect fails on write
        bad_path = tmp_path / "nonexistent" / "subdir" / "db.sqlite"
        result = log_token_usage(
            response,
            caller="test_caller",
            model="claude-haiku-4-5-20251001",
            db_path=bad_path,
        )
        assert result == {}

    def test_cache_tokens_recorded_correctly(self, test_db):
        response = _mock_response(input_tokens=500, output_tokens=200, cache_read=150, cache_create=75)
        log_token_usage(
            response,
            caller="cache_test",
            model="claude-sonnet-4-5-20250929",
            db_path=test_db,
        )

        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT cache_read_tokens, cache_creation_tokens FROM api_token_logs WHERE caller='cache_test'").fetchone()
        conn.close()
        assert row[0] == 150
        assert row[1] == 75

    def test_none_cache_tokens_default_to_zero(self, test_db):
        response = MagicMock()
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        response.usage.cache_read_input_tokens = None
        response.usage.cache_creation_input_tokens = None

        result = log_token_usage(
            response,
            caller="none_cache",
            model="claude-haiku-4-5-20251001",
            db_path=test_db,
        )

        assert result["cache_read_tokens"] == 0
        assert result["cache_creation_tokens"] == 0

    def test_cost_stored_in_db(self, test_db):
        response = _mock_response(input_tokens=1000, output_tokens=500, cache_read=0, cache_create=0)
        result = log_token_usage(
            response,
            caller="cost_check",
            model="claude-haiku-4-5-20251001",
            db_path=test_db,
        )

        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT cost_estimate_usd FROM api_token_logs WHERE caller='cost_check'").fetchone()
        conn.close()
        assert row[0] == pytest.approx(result["cost_estimate_usd"], abs=1e-6)

    def test_multiple_logs(self, test_db):
        for i in range(3):
            response = _mock_response(input_tokens=100 * (i + 1), output_tokens=50)
            log_token_usage(
                response,
                caller=f"multi_{i}",
                model="claude-haiku-4-5-20251001",
                db_path=test_db,
            )

        conn = sqlite3.connect(str(test_db))
        count = conn.execute("SELECT COUNT(*) FROM api_token_logs").fetchone()[0]
        conn.close()
        assert count == 3

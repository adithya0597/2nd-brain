"""Tests for /brain-engage command integration."""
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("config", MagicMock())

import pytest
from core.formatter import format_engagement_report


class TestFormatEngagementReport:
    def test_full_data(self):
        data = {
            "brain_level": [{"level": 7.2, "consistency": 0.8, "breadth": 0.6,
                           "depth": 0.7, "growth": 0.5, "momentum": 0.6}],
            "dimension_signals": [
                {"dimension": "Health", "touchpoints": 12, "momentum": "hot", "trend": "rising"},
                {"dimension": "Wealth", "touchpoints": 3, "momentum": "cold", "trend": "declining"},
            ],
            "engagement_7d": [
                {"date": "2026-03-07", "engagement_score": 7.5},
                {"date": "2026-03-06", "engagement_score": 6.2},
            ],
            "active_alerts": [
                {"alert_type": "neglected_dimension", "severity": "warning",
                 "title": "Wealth neglected", "detail": "Only 3 touches in 7 days"},
            ],
            "engagement_30d_avg": [{"avg_score": 6.5, "avg_journals": 1.2,
                                     "avg_completed": 3.4, "days_tracked": 28}],
        }
        blocks = format_engagement_report(data)
        assert len(blocks) > 5
        assert blocks[0]["type"] == "header"
        # Check brain level bar is present
        text_blocks = [b for b in blocks if b.get("type") == "section"]
        assert any("Brain Level" in str(b) for b in text_blocks)

    def test_empty_data(self):
        blocks = format_engagement_report({})
        # Should have at least header + divider
        assert len(blocks) >= 2
        assert blocks[0]["type"] == "header"

    def test_engage_in_command_map(self):
        from handlers.commands import _COMMAND_MAP, _AUTO_VAULT_WRITE_COMMANDS
        assert "/brain-engage" in _COMMAND_MAP
        assert _COMMAND_MAP["/brain-engage"][0] == "engage"
        assert "engage" in _AUTO_VAULT_WRITE_COMMANDS

    def test_engage_in_context_loader(self):
        from core.context_loader import _COMMAND_QUERIES
        assert "engage" in _COMMAND_QUERIES
        assert "brain_level" in _COMMAND_QUERIES["engage"]
        assert "engagement_7d" in _COMMAND_QUERIES["engage"]
        assert "dimension_signals" in _COMMAND_QUERIES["engage"]

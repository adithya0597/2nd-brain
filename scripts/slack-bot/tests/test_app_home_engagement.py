"""Tests for App Home engagement sections: brain level, dimension momentum, alerts, engagement trend."""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure slack-bot dir on path and mocks in place
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

sys.modules.setdefault("slack_sdk", MagicMock())
sys.modules.setdefault("slack_bolt", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("schedule", MagicMock())
sys.modules.setdefault("aiosqlite", MagicMock())
sys.modules.setdefault("sentence_transformers", MagicMock())
sys.modules.setdefault("sqlite_vec", MagicMock())

# Mock missing core modules that core/__init__.py tries to import
sys.modules.setdefault("core.context_loader", MagicMock())
sys.modules.setdefault("core.vault_ops", MagicMock())
sys.modules.setdefault("core.formatter", MagicMock())

from core.app_home_builder import (
    build_app_home_view,
    _build_brain_level_section,
    _build_dimension_momentum_section,
    _build_active_alerts_section,
    _build_engagement_trend_section,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_text(blocks: list[dict]) -> str:
    """Extract all visible text from a list of Block Kit blocks."""
    parts = []
    for b in blocks:
        if b.get("type") == "section":
            parts.append(b["text"]["text"])
        elif b.get("type") == "header":
            parts.append(b["text"]["text"])
        elif b.get("type") == "context":
            for el in b.get("elements", []):
                parts.append(el.get("text", ""))
    return "\n".join(parts)


def _find_header_order(blocks: list[dict]) -> list[str]:
    """Return list of header texts in order."""
    return [b["text"]["text"] for b in blocks if b.get("type") == "header"]


# ---------------------------------------------------------------------------
# Tests: Brain Level Section
# ---------------------------------------------------------------------------

class TestBrainLevelSection:
    def test_brain_level_no_data(self, test_db):
        blocks = _build_brain_level_section(db_path=test_db)
        text = _all_text(blocks)
        assert "Computing..." in text

    def test_brain_level_with_data(self, test_db):
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            """INSERT INTO brain_level
               (period, level, consistency_score, breadth_score, depth_score,
                growth_score, momentum_score, days_active, total_captures,
                total_actions_completed, hot_dimensions, frozen_dimensions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("2026-W10", 7, 0.8, 0.6, 0.5, 0.9, 0.7, 14, 50, 12, 3, 1),
        )
        conn.commit()
        conn.close()

        blocks = _build_brain_level_section(db_path=test_db)
        text = _all_text(blocks)

        # Check level bar: 7 filled blocks and 3 empty
        assert "Level 7/10" in text
        assert "\u2588" * 7 in text  # 7 filled
        assert "\u2591" * 3 in text  # 3 empty

        # Check component breakdown
        assert "C:0.8" in text
        assert "B:0.6" in text
        assert "D:0.5" in text
        assert "G:0.9" in text
        assert "M:0.7" in text

        # Check days active and period
        assert "Days active: 14" in text
        assert "2026-W10" in text


# ---------------------------------------------------------------------------
# Tests: Dimension Momentum Section
# ---------------------------------------------------------------------------

class TestDimensionMomentumSection:
    def test_dimension_momentum_no_data(self, test_db):
        blocks = _build_dimension_momentum_section(db_path=test_db)
        text = _all_text(blocks)
        assert "Computing..." in text

    def test_dimension_momentum_with_data(self, test_db):
        conn = sqlite3.connect(str(test_db))
        today = datetime.now().strftime("%Y-%m-%d")
        dimensions = [
            ("Health & Vitality", "hot", "rising"),
            ("Wealth & Finance", "warm", "stable"),
            ("Relationships", "cold", "declining"),
            ("Mind & Growth", "hot", "rising"),
            ("Purpose & Impact", "frozen", "declining"),
            ("Systems & Environment", "warm", "stable"),
        ]
        for dim, momentum, trend in dimensions:
            conn.execute(
                """INSERT INTO dimension_signals
                   (date, dimension, momentum, trend)
                   VALUES (?, ?, ?, ?)""",
                (today, dim, momentum, trend),
            )
        conn.commit()
        conn.close()

        blocks = _build_dimension_momentum_section(db_path=test_db)
        text = _all_text(blocks)

        # All 6 short dimension names should appear
        for short_name in ["Health", "Wealth", "Relationships", "Mind", "Purpose", "Systems"]:
            assert short_name in text

        # Check momentum words present
        assert "hot" in text
        assert "warm" in text
        assert "cold" in text
        assert "frozen" in text

        # Check trend arrows present
        assert "\u2191" in text  # rising
        assert "\u2192" in text  # stable
        assert "\u2193" in text  # declining


# ---------------------------------------------------------------------------
# Tests: Active Alerts Section
# ---------------------------------------------------------------------------

class TestActiveAlertsSection:
    def test_alerts_no_data(self, test_db):
        blocks = _build_active_alerts_section(db_path=test_db)
        # Implementation returns empty list when no active alerts
        assert blocks == []

    def test_alerts_with_data(self, test_db):
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            """INSERT INTO alerts
               (alert_type, severity, title, status, fingerprint)
               VALUES (?, ?, ?, ?, ?)""",
            ("drift", "critical", "Health dimension neglected for 14 days", "active", "fp1"),
        )
        conn.execute(
            """INSERT INTO alerts
               (alert_type, severity, title, status, fingerprint)
               VALUES (?, ?, ?, ?, ?)""",
            ("engagement_drop", "info", "Engagement dropped below 3.0", "active", "fp2"),
        )
        conn.commit()
        conn.close()

        blocks = _build_active_alerts_section(db_path=test_db)
        text = _all_text(blocks)

        # Critical should appear first
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section"
        ]
        # First section text (after any "No active alerts") should be critical
        assert "[!!]" in section_texts[0]
        assert "Health dimension neglected" in section_texts[0]

        # Info alert with [i] should also appear
        assert "[i]" in text
        assert "Engagement dropped" in text

        # Dismiss buttons should be present
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 2
        for ab in action_blocks:
            elements = ab["elements"]
            assert any(e["action_id"] == "app_home_dismiss_alert" for e in elements)

    def test_alerts_dismissed_not_shown(self, test_db):
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            """INSERT INTO alerts
               (alert_type, severity, title, status, dismissed_at, fingerprint)
               VALUES (?, ?, ?, ?, datetime('now'), ?)""",
            ("drift", "warning", "Old dismissed alert", "dismissed", "fp_old"),
        )
        conn.commit()
        conn.close()

        blocks = _build_active_alerts_section(db_path=test_db)
        text = _all_text(blocks)

        assert "Old dismissed alert" not in text
        # Only dismissed alerts exist, so no active alerts — empty list returned
        assert blocks == []


# ---------------------------------------------------------------------------
# Tests: Engagement Trend Section
# ---------------------------------------------------------------------------

class TestEngagementTrendSection:
    def test_engagement_trend_no_data(self, test_db):
        blocks = _build_engagement_trend_section(db_path=test_db)
        text = _all_text(blocks)
        assert "Computing..." in text

    def test_engagement_trend_with_data(self, test_db):
        conn = sqlite3.connect(str(test_db))
        base = datetime(2026, 3, 2)  # Monday
        for i in range(7):
            d = base + timedelta(days=i)
            score = 3.0 + i * 1.0  # 3.0 to 9.0
            conn.execute(
                "INSERT INTO engagement_daily (date, engagement_score) VALUES (?, ?)",
                (d.strftime("%Y-%m-%d"), score),
            )
        conn.commit()
        conn.close()

        blocks = _build_engagement_trend_section(db_path=test_db)
        text = _all_text(blocks)

        # Should have day abbreviations
        assert "Mon" in text
        assert "Sun" in text

        # Should have filled and empty blocks
        assert "\u2588" in text
        assert "\u2591" in text

        # Should have score values
        assert "3.0" in text
        assert "9.0" in text

    def test_engagement_trend_avg(self, test_db):
        conn = sqlite3.connect(str(test_db))
        base = datetime(2026, 3, 2)  # Monday
        scores = [4.0, 6.0, 8.0, 5.0, 7.0, 3.0, 9.0]
        for i, score in enumerate(scores):
            d = base + timedelta(days=i)
            conn.execute(
                "INSERT INTO engagement_daily (date, engagement_score) VALUES (?, ?)",
                (d.strftime("%Y-%m-%d"), score),
            )
        conn.commit()
        conn.close()

        blocks = _build_engagement_trend_section(db_path=test_db)
        text = _all_text(blocks)

        expected_avg = sum(scores) / len(scores)  # 6.0
        assert f"Avg: {expected_avg:.1f}/10" in text


# ---------------------------------------------------------------------------
# Tests: Full View Integration
# ---------------------------------------------------------------------------

class TestFullViewIntegration:
    def test_full_view_section_order(self, test_db):
        view = build_app_home_view("U123", db_path=test_db)
        headers = _find_header_order(view["blocks"])

        # With empty data, ALERTS section returns [] (no header).
        # Only sections that always produce headers are expected.
        expected_order = [
            "BRAIN LEVEL",
            "DIMENSION MOMENTUM",
            "SECOND BRAIN DASHBOARD",
            "7-DAY ENGAGEMENT",
        ]
        # Verify the headers appear in the expected order
        assert headers == expected_order

    def test_full_view_block_count(self, test_db):
        view = build_app_home_view("U123", db_path=test_db)
        # Slack limit is 100 blocks per view
        assert len(view["blocks"]) < 100

    def test_full_view_type(self, test_db):
        view = build_app_home_view("U123", db_path=test_db)
        assert view["type"] == "home"
        assert isinstance(view["blocks"], list)

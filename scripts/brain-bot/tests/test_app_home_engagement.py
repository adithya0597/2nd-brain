"""Tests for dashboard engagement sections: brain level, dimension momentum, alerts, engagement trend."""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock


# Ensure brain-bot dir on path and mocks in place
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("aiosqlite", MagicMock())
sys.modules.setdefault("sentence_transformers", MagicMock())
sys.modules.setdefault("sqlite_vec", MagicMock())

from core.dashboard_builder import (
    build_dashboard_view,
    _build_brain_level_section,
    _build_dimension_momentum_section,
    _build_active_alerts_section,
    _build_engagement_trend_section,
)


# ---------------------------------------------------------------------------
# Tests: Brain Level Section
# ---------------------------------------------------------------------------

class TestBrainLevelSection:
    def test_brain_level_no_data(self, test_db):
        text = _build_brain_level_section(db_path=test_db)
        assert isinstance(text, str)
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

        text = _build_brain_level_section(db_path=test_db)

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
        text = _build_dimension_momentum_section(db_path=test_db)
        assert isinstance(text, str)
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

        text = _build_dimension_momentum_section(db_path=test_db)

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
        html, keyboard_rows = _build_active_alerts_section(db_path=test_db)
        assert html == ""
        assert keyboard_rows == []

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

        html, keyboard_rows = _build_active_alerts_section(db_path=test_db)

        # HTML should contain alert titles
        assert "Health dimension neglected" in html
        assert "Engagement dropped" in html

        # Should have ALERTS header
        assert "ALERTS" in html

        # Keyboard rows should have dismiss buttons (one per alert)
        assert len(keyboard_rows) == 2

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

        html, keyboard_rows = _build_active_alerts_section(db_path=test_db)

        # Only dismissed alerts exist, so no active alerts
        assert html == ""
        assert keyboard_rows == []


# ---------------------------------------------------------------------------
# Tests: Engagement Trend Section
# ---------------------------------------------------------------------------

class TestEngagementTrendSection:
    def test_engagement_trend_no_data(self, test_db):
        text = _build_engagement_trend_section(db_path=test_db)
        assert isinstance(text, str)
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

        text = _build_engagement_trend_section(db_path=test_db)

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

        text = _build_engagement_trend_section(db_path=test_db)

        expected_avg = sum(scores) / len(scores)  # 6.0
        assert f"Avg: {expected_avg:.1f}/10" in text


# ---------------------------------------------------------------------------
# Tests: Full View Integration
# ---------------------------------------------------------------------------

class TestFullViewIntegration:
    def test_full_view_returns_html_and_keyboard(self, test_db):
        html, keyboard = build_dashboard_view(db_path=test_db)

        # html should be a plain string
        assert isinstance(html, str)

        # Should contain all major section headers
        assert "BRAIN LEVEL" in html
        assert "DIMENSION MOMENTUM" in html
        assert "SECOND BRAIN DASHBOARD" in html
        assert "7-DAY ENGAGEMENT" in html

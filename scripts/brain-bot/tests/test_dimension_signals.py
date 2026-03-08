"""Tests for core.dimension_signals — dimension momentum and Brain Level engine."""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path & module setup
# ---------------------------------------------------------------------------
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

from core.dimension_signals import (  # noqa: E402
    classify_momentum,
    classify_trend,
    compute_dimension_signals,
    compute_brain_level,
    get_latest_dimension_signals,
    get_current_brain_level,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
CURRENT_PERIOD = datetime.now().strftime("%Y-%m")


def _ts(date_str, time_str="12:00:00"):
    """Build a full timestamp string from a date and optional time."""
    return f"{date_str} {time_str}"


def _insert_capture(conn, date_str, dims_json="[]", actionable=0, method="keyword"):
    conn.execute(
        "INSERT INTO captures_log (message_text, dimensions_json, confidence, "
        "method, is_actionable, source_channel, created_at) "
        "VALUES (?, ?, 0.9, ?, ?, 'brain-inbox', ?)",
        ("test capture", dims_json, method, actionable, _ts(date_str)),
    )


def _insert_journal(conn, date_str, content="Had a good day", mood="happy",
                     energy="high", sentiment=0.7, icor_elements="[]"):
    conn.execute(
        "INSERT OR REPLACE INTO journal_entries (date, content, mood, energy, "
        "sentiment_score, icor_elements) VALUES (?, ?, ?, ?, ?, ?)",
        (date_str, content, mood, energy, sentiment, icor_elements),
    )


def _insert_action(conn, date_str, status="pending", icor_element=None,
                    completed_at=None):
    conn.execute(
        "INSERT INTO action_items (description, source_date, status, "
        "icor_element, completed_at) VALUES (?, ?, ?, ?, ?)",
        ("test action", date_str, status, icor_element, completed_at),
    )


def _insert_engagement(conn, date_str, journal_count=0, captures=0,
                         actions_created=0, actions_completed=0,
                         engagement_score=0.0, vault_created=0,
                         dim_mentions_json="{}"):
    conn.execute(
        "INSERT OR REPLACE INTO engagement_daily ("
        "date, journal_entry_count, captures_count, "
        "actions_created, actions_completed, "
        "engagement_score, vault_files_created, "
        "dimension_mentions_json, computed_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (date_str, journal_count, captures, actions_created,
         actions_completed, engagement_score, vault_created,
         dim_mentions_json),
    )


def _insert_dimension_signal(conn, date_str, dimension, momentum="cold",
                               trend="stable", rolling_30d=0, momentum_score=0.0):
    conn.execute(
        "INSERT OR REPLACE INTO dimension_signals ("
        "date, dimension, momentum, trend, rolling_30d_mentions, "
        "momentum_score, computed_at"
        ") VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (date_str, dimension, momentum, trend, rolling_30d, momentum_score),
    )


def _insert_brain_level(conn, period, level, consistency=0.0, breadth=0.0,
                          depth=0.0, growth=0.0, momentum=0.0):
    conn.execute(
        "INSERT OR REPLACE INTO brain_level ("
        "period, level, consistency_score, breadth_score, depth_score, "
        "growth_score, momentum_score, computed_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (period, level, consistency, breadth, depth, growth, momentum),
    )


# ===========================================================================
# classify_momentum tests
# ===========================================================================


class TestClassifyMomentum:
    def test_classify_momentum_hot(self):
        assert classify_momentum(10) == "hot"
        assert classify_momentum(15) == "hot"
        assert classify_momentum(100) == "hot"

    def test_classify_momentum_warm(self):
        assert classify_momentum(4) == "warm"
        assert classify_momentum(5) == "warm"
        assert classify_momentum(9) == "warm"

    def test_classify_momentum_cold(self):
        assert classify_momentum(1) == "cold"
        assert classify_momentum(2) == "cold"
        assert classify_momentum(3) == "cold"

    def test_classify_momentum_frozen(self):
        assert classify_momentum(0) == "frozen"


# ===========================================================================
# classify_trend tests
# ===========================================================================


class TestClassifyTrend:
    def test_classify_trend_rising(self):
        # 13/10 = 1.3, exactly the threshold
        assert classify_trend(13, 10) == "rising"
        assert classify_trend(20, 10) == "rising"

    def test_classify_trend_declining(self):
        # 7/10 = 0.7, exactly the threshold
        assert classify_trend(7, 10) == "declining"
        assert classify_trend(3, 10) == "declining"

    def test_classify_trend_stable(self):
        assert classify_trend(10, 10) == "stable"
        assert classify_trend(8, 10) == "stable"
        assert classify_trend(12, 10) == "stable"

    def test_classify_trend_zero_to_positive(self):
        assert classify_trend(5, 0) == "rising"
        assert classify_trend(1, 0) == "rising"

    def test_classify_trend_both_zero(self):
        assert classify_trend(0, 0) == "stable"


# ===========================================================================
# compute_dimension_signals tests
# ===========================================================================


class TestComputeSignalsEmptyDB:
    """On an empty database, all 6 dimensions should be frozen/stable."""

    def test_compute_signals_empty_db(self, test_db):
        signals = compute_dimension_signals(TODAY, db_path=test_db)

        assert len(signals) == 6
        dims = {s["dimension"] for s in signals}
        assert dims == {
            "Health & Vitality", "Wealth & Finance", "Relationships",
            "Mind & Growth", "Purpose & Impact", "Systems & Environment",
        }
        for s in signals:
            assert s["momentum"] == "frozen"
            assert s["trend"] == "stable"
            assert s["mentions"] == 0
            assert s["captures"] == 0
            assert s["actions_created"] == 0
            assert s["actions_completed"] == 0


class TestComputeSignalsWithData:
    """Inserting captures and actions should produce non-zero metrics."""

    def test_compute_signals_with_data(self, test_db):
        conn = sqlite3.connect(str(test_db))

        # Insert captures mentioning Health & Vitality for today
        _insert_capture(
            conn, TODAY,
            dims_json=json.dumps(["Health & Vitality"]),
        )
        _insert_capture(
            conn, TODAY,
            dims_json=json.dumps(["Health & Vitality"]),
        )

        # Insert a journal entry mentioning Health & Vitality
        _insert_journal(
            conn, TODAY,
            icor_elements=json.dumps(["Health & Vitality"]),
        )

        # Insert an action linked to Health & Vitality
        _insert_action(
            conn, TODAY, status="pending",
            icor_element="Health & Vitality",
        )

        conn.commit()
        conn.close()

        signals = compute_dimension_signals(TODAY, db_path=test_db)

        health = next(s for s in signals if s["dimension"] == "Health & Vitality")
        assert health["captures"] == 2
        assert health["mentions"] == 1
        assert health["actions_created"] == 1

        # Other dimensions should still be frozen
        wealth = next(s for s in signals if s["dimension"] == "Wealth & Finance")
        assert wealth["captures"] == 0
        assert wealth["momentum"] == "frozen"


# ===========================================================================
# compute_brain_level tests
# ===========================================================================


class TestBrainLevelEmptyDB:
    """On an empty database, brain level should be 1 with all scores at 0."""

    def test_brain_level_empty_db(self, test_db):
        result = compute_brain_level(CURRENT_PERIOD, db_path=test_db)

        assert result["period"] == CURRENT_PERIOD
        assert result["level"] == 1
        assert result["consistency_score"] == 0.0
        assert result["breadth_score"] == 0.0
        assert result["depth_score"] == 0.0
        assert result["growth_score"] == 0.0
        # momentum_score: 0.0 / 0.1 * 5 = 0.0
        assert result["momentum_score"] == 0.0


class TestBrainLevelWithEngagementData:
    """With engagement data, brain level should reflect the sub-scores."""

    def test_brain_level_with_engagement_data(self, test_db):
        conn = sqlite3.connect(str(test_db))

        # Insert engagement rows for several days in the current period
        base = datetime.now().date()
        for i in range(10):
            d = (base - timedelta(days=i)).isoformat()
            if d.startswith(CURRENT_PERIOD):
                _insert_engagement(
                    conn, d,
                    journal_count=1,
                    captures=3,
                    actions_created=2,
                    actions_completed=1,
                    engagement_score=5.0,
                    vault_created=1,
                    dim_mentions_json=json.dumps({
                        "Health & Vitality": 2,
                        "Mind & Growth": 1,
                    }),
                )

        # Insert dimension signals with rolling_30d > 0
        for d_offset in range(10):
            d = (base - timedelta(days=d_offset)).isoformat()
            if d.startswith(CURRENT_PERIOD):
                _insert_dimension_signal(
                    conn, d, "Health & Vitality",
                    momentum="warm", rolling_30d=5,
                )
                _insert_dimension_signal(
                    conn, d, "Mind & Growth",
                    momentum="cold", rolling_30d=2,
                )

        conn.commit()
        conn.close()

        result = compute_brain_level(CURRENT_PERIOD, db_path=test_db)

        assert result["level"] >= 1
        assert result["level"] <= 10
        assert result["consistency_score"] > 0
        assert result["breadth_score"] > 0
        assert result["depth_score"] > 0


class TestBrainLevelClamped:
    """Brain level must be between 1 and 10 inclusive."""

    def test_brain_level_clamped_1_to_10(self, test_db):
        # Empty DB -> level 1 (not 0)
        result_low = compute_brain_level(CURRENT_PERIOD, db_path=test_db)
        assert result_low["level"] >= 1

        # Artificially high scores can't exceed 10
        conn = sqlite3.connect(str(test_db))
        base = datetime.now().date()
        year = base.year
        month = base.month
        import calendar as cal
        days_in = cal.monthrange(year, month)[1]

        for day_num in range(1, days_in + 1):
            d = f"{year:04d}-{month:02d}-{day_num:02d}"
            _insert_engagement(
                conn, d,
                journal_count=1,
                captures=20,
                actions_created=10,
                actions_completed=10,
                engagement_score=10.0,
                vault_created=10,
            )
            # All 6 dimensions active
            for dim in [
                "Health & Vitality", "Wealth & Finance", "Relationships",
                "Mind & Growth", "Purpose & Impact", "Systems & Environment",
            ]:
                _insert_dimension_signal(conn, d, dim, rolling_30d=50, momentum="hot")

        # Also add a bunch of concept promotions
        for i in range(50):
            conn.execute(
                "INSERT OR IGNORE INTO concept_metadata (title, created_at) "
                "VALUES (?, ?)",
                (f"concept-{i}", f"{CURRENT_PERIOD}-01 10:00:00"),
            )

        conn.commit()
        conn.close()

        result_high = compute_brain_level(CURRENT_PERIOD, db_path=test_db)
        assert result_high["level"] <= 10
        assert result_high["level"] >= 1


# ===========================================================================
# get_latest_dimension_signals tests
# ===========================================================================


class TestGetLatestSignals:
    """get_latest_dimension_signals should return signals for the most recent date."""

    def test_get_latest_signals(self, test_db):
        conn = sqlite3.connect(str(test_db))

        # Insert signals for two dates
        for dim in [
            "Health & Vitality", "Wealth & Finance", "Relationships",
            "Mind & Growth", "Purpose & Impact", "Systems & Environment",
        ]:
            _insert_dimension_signal(conn, YESTERDAY, dim, momentum="cold")
            _insert_dimension_signal(conn, TODAY, dim, momentum="warm")

        conn.commit()
        conn.close()

        signals = get_latest_dimension_signals(db_path=test_db)

        assert len(signals) == 6
        for s in signals:
            assert s["date"] == TODAY
            assert s["momentum"] == "warm"


# ===========================================================================
# get_current_brain_level tests
# ===========================================================================


class TestGetCurrentBrainLevel:
    def test_get_current_brain_level_none(self, test_db):
        """Empty DB returns None."""
        result = get_current_brain_level(db_path=test_db)
        assert result is None

    def test_get_current_brain_level_exists(self, test_db):
        """Inserted brain_level row is returned."""
        conn = sqlite3.connect(str(test_db))
        _insert_brain_level(conn, CURRENT_PERIOD, level=5,
                             consistency=6.0, breadth=4.0, depth=5.0,
                             growth=3.0, momentum=7.0)
        conn.commit()
        conn.close()

        result = get_current_brain_level(db_path=test_db)

        assert result is not None
        assert result["period"] == CURRENT_PERIOD
        assert result["level"] == 5
        assert result["consistency_score"] == 6.0
        assert result["breadth_score"] == 4.0

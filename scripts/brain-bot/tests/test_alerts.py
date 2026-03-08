"""Tests for core.alerts — pattern detection and alert management."""

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

sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("schedule", MagicMock())
sys.modules.setdefault("aiosqlite", MagicMock())
sys.modules.setdefault("sentence_transformers", MagicMock())
sys.modules.setdefault("sqlite_vec", MagicMock())

from core.alerts import (  # noqa: E402
    _fingerprint,
    _create_alert,
    check_stale_actions,
    check_neglected_dimensions,
    check_engagement_drop,
    check_streak_break,
    check_drift_alerts,
    check_knowledge_gaps,
    run_all_checks,
    dismiss_alert,
    get_active_alerts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _ts(date_str, time_str="12:00:00"):
    """Build a full timestamp string."""
    return f"{date_str} {time_str}"


def _days_ago(n):
    """Return ISO date string for *n* days ago."""
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _count_alerts(db_path, where=""):
    conn = sqlite3.connect(str(db_path))
    sql = "SELECT COUNT(*) FROM alerts"
    if where:
        sql += f" WHERE {where}"
    result = conn.execute(sql).fetchone()[0]
    conn.close()
    return result


# ===========================================================================
# Fingerprint tests
# ===========================================================================


class TestFingerprint:
    def test_fingerprint_deterministic(self):
        """Same inputs produce the same hash."""
        fp1 = _fingerprint("stale_actions", "Health & Vitality", "42")
        fp2 = _fingerprint("stale_actions", "Health & Vitality", "42")
        assert fp1 == fp2
        assert len(fp1) == 32  # MD5 hex digest

    def test_fingerprint_different_inputs(self):
        """Different inputs produce different hashes."""
        fp1 = _fingerprint("stale_actions", key="1")
        fp2 = _fingerprint("stale_actions", key="2")
        fp3 = _fingerprint("drift", key="1")
        assert fp1 != fp2
        assert fp1 != fp3


# ===========================================================================
# Alert creation tests
# ===========================================================================


class TestCreateAlert:
    def test_create_alert_success(self, test_db):
        """Creating an alert inserts a row in the DB."""
        result = _create_alert(
            alert_type="stale_actions",
            severity="warning",
            title="Test alert",
            key="test-1",
            db_path=test_db,
        )
        assert result is True
        assert _count_alerts(test_db) == 1

    def test_create_alert_dedup(self, test_db):
        """Creating the same fingerprint twice returns False the second time."""
        first = _create_alert(
            alert_type="stale_actions",
            severity="warning",
            title="Test alert",
            key="test-dedup",
            db_path=test_db,
        )
        second = _create_alert(
            alert_type="stale_actions",
            severity="warning",
            title="Test alert (different title, same fingerprint)",
            key="test-dedup",
            db_path=test_db,
        )
        assert first is True
        assert second is False
        assert _count_alerts(test_db) == 1


# ===========================================================================
# Stale actions tests
# ===========================================================================


class TestStaleActions:
    def test_check_stale_actions_none(self, test_db):
        """No pending actions means 0 alerts."""
        result = check_stale_actions(days_threshold=7, db_path=test_db)
        assert result == 0

    def test_check_stale_actions_found(self, test_db):
        """An old pending action triggers an alert."""
        conn = sqlite3.connect(str(test_db))
        old_date = _ts(_days_ago(8))
        conn.execute(
            "INSERT INTO action_items (description, status, created_at) "
            "VALUES (?, 'pending', ?)",
            ("Review quarterly goals", old_date),
        )
        conn.commit()
        conn.close()

        result = check_stale_actions(days_threshold=7, db_path=test_db)
        assert result == 1
        assert _count_alerts(test_db, "alert_type = 'stale_actions'") == 1


# ===========================================================================
# Neglected dimensions tests
# ===========================================================================


class TestNeglectedDimensions:
    def test_check_neglected_dimensions(self, test_db):
        """Empty captures and journal tables means all 6 dimensions are neglected."""
        result = check_neglected_dimensions(days_threshold=14, db_path=test_db)
        assert result == 6
        assert _count_alerts(test_db, "alert_type = 'neglected_dimension'") == 6

    def test_check_neglected_dimensions_active(self, test_db):
        """A dimension with recent captures should NOT trigger an alert."""
        conn = sqlite3.connect(str(test_db))
        recent = _ts(_days_ago(3))
        conn.execute(
            "INSERT INTO captures_log (message_text, dimensions_json, confidence, "
            "method, is_actionable, source_channel, created_at) "
            "VALUES (?, ?, 0.9, 'keyword', 0, 'brain-inbox', ?)",
            ("Went for a run", json.dumps(["Health & Vitality"]), recent),
        )
        conn.commit()
        conn.close()

        result = check_neglected_dimensions(days_threshold=14, db_path=test_db)
        # 5 neglected (Health & Vitality is active)
        assert result == 5
        assert _count_alerts(test_db, "alert_type = 'neglected_dimension'") == 5


# ===========================================================================
# Engagement drop tests
# ===========================================================================


class TestEngagementDrop:
    def test_check_engagement_drop_no_data(self, test_db):
        """Empty engagement_daily returns 0 alerts."""
        result = check_engagement_drop(db_path=test_db)
        assert result == 0

    def test_check_engagement_drop_detected(self, test_db):
        """High scores in previous week and low in current triggers an alert."""
        conn = sqlite3.connect(str(test_db))
        today = datetime.now().date()

        # Previous week: high engagement (8.0)
        for i in range(7, 14):
            d = (today - timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT INTO engagement_daily (date, engagement_score) VALUES (?, ?)",
                (d, 8.0),
            )

        # Current week: very low engagement (1.0)
        for i in range(0, 7):
            d = (today - timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT INTO engagement_daily (date, engagement_score) VALUES (?, ?)",
                (d, 1.0),
            )

        conn.commit()
        conn.close()

        result = check_engagement_drop(threshold=0.5, db_path=test_db)
        assert result == 1
        assert _count_alerts(test_db, "alert_type = 'engagement_drop'") == 1

        # Verify severity is critical (current_avg=1.0 < 2)
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        alert = conn.execute(
            "SELECT * FROM alerts WHERE alert_type = 'engagement_drop'"
        ).fetchone()
        conn.close()
        assert dict(alert)["severity"] == "critical"


# ===========================================================================
# Streak break tests
# ===========================================================================


class TestStreakBreak:
    def test_check_streak_break_no_streak(self, test_db):
        """No journal entries at all means no streak to break."""
        result = check_streak_break(db_path=test_db)
        assert result == 0

    def test_check_streak_break_detected(self, test_db):
        """Journal for 3 days before yesterday but NOT yesterday triggers alert."""
        conn = sqlite3.connect(str(test_db))
        # Insert entries for 2, 3, 4 days ago (but NOT yesterday)
        for offset in [2, 3, 4]:
            d = _days_ago(offset)
            conn.execute(
                "INSERT OR REPLACE INTO journal_entries (date, content) "
                "VALUES (?, ?)",
                (d, f"Journal for {d}"),
            )
        conn.commit()
        conn.close()

        result = check_streak_break(db_path=test_db)
        assert result == 1
        assert _count_alerts(test_db, "alert_type = 'streak_break'") == 1


# ===========================================================================
# Drift alerts tests
# ===========================================================================


class TestDriftAlerts:
    def test_check_drift_alerts_no_data(self, test_db):
        """No engagement data means no drift alerts."""
        result = check_drift_alerts(db_path=test_db)
        assert result == 0

    def test_check_drift_alerts_detected(self, test_db):
        """A dimension dropping 60%+ in mentions triggers a drift alert."""
        conn = sqlite3.connect(str(test_db))
        today = datetime.now().date()

        # Previous 14 days: Health mentioned 10 times per day
        for i in range(14, 28):
            d = (today - timedelta(days=i)).isoformat()
            mentions = json.dumps({"Health & Vitality": 10, "Mind & Growth": 5})
            conn.execute(
                "INSERT INTO engagement_daily (date, dimension_mentions_json, "
                "engagement_score) VALUES (?, ?, 5.0)",
                (d, mentions),
            )

        # Current 14 days: Health mentioned only 1 time per day (90% drop)
        for i in range(0, 14):
            d = (today - timedelta(days=i)).isoformat()
            mentions = json.dumps({"Health & Vitality": 1, "Mind & Growth": 5})
            conn.execute(
                "INSERT INTO engagement_daily (date, dimension_mentions_json, "
                "engagement_score) VALUES (?, ?, 5.0)",
                (d, mentions),
            )

        conn.commit()
        conn.close()

        result = check_drift_alerts(db_path=test_db)
        # Health & Vitality dropped 90%, Mind & Growth stable
        assert result >= 1
        assert _count_alerts(test_db, "alert_type = 'drift'") >= 1


# ===========================================================================
# Knowledge gaps tests
# ===========================================================================


class TestKnowledgeGaps:
    def test_check_knowledge_gaps(self, test_db):
        """Vault nodes with no edges should be flagged as knowledge gaps."""
        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        # Insert isolated document nodes (no edges)
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type) "
            "VALUES ('Notes/orphan1.md', 'Orphan Note 1', 'note', 'document')"
        )
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type) "
            "VALUES ('Notes/orphan2.md', 'Orphan Note 2', 'note', 'document')"
        )
        conn.commit()
        conn.close()

        result = check_knowledge_gaps(min_edges=2, db_path=test_db)
        assert result >= 2
        assert _count_alerts(test_db, "alert_type = 'knowledge_gap'") >= 2


# ===========================================================================
# Run all checks test
# ===========================================================================


class TestRunAllChecks:
    def test_run_all_checks(self, test_db):
        """run_all_checks returns a dict with total_new and by_type."""
        result = run_all_checks(db_path=test_db)
        assert "total_new" in result
        assert "by_type" in result
        assert isinstance(result["total_new"], int)
        assert isinstance(result["by_type"], dict)
        # Should contain all 6 check types
        expected_types = {
            "stale_actions",
            "neglected_dimension",
            "engagement_drop",
            "streak_break",
            "drift",
            "knowledge_gap",
        }
        assert set(result["by_type"].keys()) == expected_types


# ===========================================================================
# Management function tests
# ===========================================================================


class TestDismissAlert:
    def test_dismiss_alert(self, test_db):
        """Dismissing an active alert sets status to 'dismissed'."""
        _create_alert(
            alert_type="stale_actions",
            severity="warning",
            title="Alert to dismiss",
            key="dismiss-test",
            db_path=test_db,
        )

        conn = sqlite3.connect(str(test_db))
        alert_id = conn.execute(
            "SELECT id FROM alerts WHERE fingerprint = ?",
            (_fingerprint("stale_actions", key="dismiss-test"),),
        ).fetchone()[0]
        conn.close()

        result = dismiss_alert(alert_id, db_path=test_db)
        assert result is True

        # Verify status changed
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, dismissed_at FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        conn.close()
        assert dict(row)["status"] == "dismissed"
        assert dict(row)["dismissed_at"] is not None

    def test_dismiss_nonexistent(self, test_db):
        """Dismissing a non-existent alert returns False."""
        result = dismiss_alert(99999, db_path=test_db)
        assert result is False


# ===========================================================================
# Get active alerts tests
# ===========================================================================


class TestGetActiveAlerts:
    def test_get_active_alerts_empty(self, test_db):
        """Empty DB returns an empty list."""
        result = get_active_alerts(db_path=test_db)
        assert result == []

    def test_get_active_alerts_ordered(self, test_db):
        """Critical alerts appear before info alerts."""
        _create_alert(
            alert_type="streak_break",
            severity="info",
            title="Info alert",
            key="order-info",
            db_path=test_db,
        )
        _create_alert(
            alert_type="engagement_drop",
            severity="critical",
            title="Critical alert",
            key="order-critical",
            db_path=test_db,
        )
        _create_alert(
            alert_type="stale_actions",
            severity="warning",
            title="Warning alert",
            key="order-warning",
            db_path=test_db,
        )

        result = get_active_alerts(db_path=test_db)
        assert len(result) == 3
        assert result[0]["severity"] == "critical"
        assert result[1]["severity"] == "warning"
        assert result[2]["severity"] == "info"

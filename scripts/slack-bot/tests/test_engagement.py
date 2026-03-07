"""Tests for core.engagement — daily engagement metrics engine."""

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

from core.engagement import (  # noqa: E402
    compute_daily_metrics,
    save_daily_metrics,
    backfill_engagement,
    get_engagement_history,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


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
                     energy="high", sentiment=0.7):
    conn.execute(
        "INSERT OR REPLACE INTO journal_entries (date, content, mood, energy, "
        "sentiment_score) VALUES (?, ?, ?, ?, ?)",
        (date_str, content, mood, energy, sentiment),
    )


def _insert_action(conn, date_str, status="pending", completed_at=None):
    conn.execute(
        "INSERT INTO action_items (description, source_date, status, completed_at) "
        "VALUES (?, ?, ?, ?)",
        ("test action", date_str, status, completed_at),
    )


def _insert_vault_node(conn, file_path, title, node_type="document",
                        file_type="journal", indexed_at=None):
    indexed_at = indexed_at or _ts(TODAY)
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, type, node_type, indexed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_path, title, file_type, node_type, indexed_at),
    )


def _insert_vault_edge(conn, source_id, target_id, edge_type="wikilink",
                         created_at=None):
    created_at = created_at or _ts(TODAY)
    conn.execute(
        "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type, created_at) "
        "VALUES (?, ?, ?, ?)",
        (source_id, target_id, edge_type, created_at),
    )


def _count_rows(db_path, table, where=""):
    conn = sqlite3.connect(str(db_path))
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    result = conn.execute(sql).fetchone()[0]
    conn.close()
    return result


# ===========================================================================
# Tests
# ===========================================================================


class TestComputeEmptyDB:
    """Verify compute on an empty database returns zeros."""

    def test_compute_empty_db(self, test_db):
        metrics = compute_daily_metrics(TODAY, db_path=test_db)

        assert metrics["date"] == TODAY
        assert metrics["captures_count"] == 0
        assert metrics["actionable_captures"] == 0
        assert metrics["actions_created"] == 0
        assert metrics["actions_completed"] == 0
        assert metrics["journal_entry_count"] == 0
        assert metrics["journal_word_count"] == 0
        assert metrics["vault_files_modified"] == 0
        assert metrics["vault_files_created"] == 0
        assert metrics["edges_created"] == 0
        assert metrics["notion_items_synced"] == 0
        assert metrics["engagement_score"] == 0


class TestComputeWithJournal:
    """Journal entry should contribute 2 points to engagement score."""

    def test_compute_with_journal_entry(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_journal(conn, TODAY, content="Today was productive and fulfilling",
                        mood="happy", energy="high", sentiment=0.8)
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)

        assert metrics["journal_entry_count"] == 1
        assert metrics["journal_word_count"] > 0
        assert metrics["mood"] == "happy"
        assert metrics["energy"] == "high"
        assert metrics["avg_sentiment"] == 0.8
        # Journal alone = 2 points
        assert metrics["engagement_score"] >= 2.0


class TestComputeWithCaptures:
    """5 captures should give max captures_score of 2."""

    def test_compute_with_captures(self, test_db):
        conn = sqlite3.connect(str(test_db))
        for i in range(5):
            _insert_capture(conn, TODAY, actionable=(1 if i < 2 else 0))
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)

        assert metrics["captures_count"] == 5
        assert metrics["actionable_captures"] == 2
        # 5/5 * 2 = 2.0
        assert metrics["engagement_score"] >= 2.0


class TestComputeWithActions:
    """Verify action item counts (created, completed, pending)."""

    def test_compute_with_actions(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # 3 created today
        _insert_action(conn, TODAY, status="pending")
        _insert_action(conn, TODAY, status="completed",
                        completed_at=_ts(TODAY, "14:00:00"))
        _insert_action(conn, TODAY, status="completed",
                        completed_at=_ts(TODAY, "15:00:00"))
        # 1 from yesterday still pending
        _insert_action(conn, YESTERDAY, status="pending")
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)

        assert metrics["actions_created"] == 3
        assert metrics["actions_completed"] == 2
        # 2 pending total (1 from today + 1 from yesterday)
        assert metrics["actions_pending"] == 2
        # actions_score = min(2/3 * 2, 2) = 1.33
        assert metrics["engagement_score"] > 0


class TestComputeDimensionMentions:
    """Dimension mentions from captures_log.dimensions_json are aggregated."""

    def test_compute_dimension_mentions(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Capture mentioning two dimensions (list format)
        _insert_capture(
            conn, TODAY,
            dims_json=json.dumps(["Health & Vitality", "Mind & Growth"]),
        )
        # Another capture mentioning one dimension
        _insert_capture(
            conn, TODAY,
            dims_json=json.dumps(["Health & Vitality"]),
        )
        # Capture with dict format
        _insert_capture(
            conn, TODAY,
            dims_json=json.dumps({"Wealth & Finance": 2}),
        )
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)

        dm = json.loads(metrics["dimension_mentions_json"])
        assert dm["Health & Vitality"] == 2
        assert dm["Mind & Growth"] == 1
        assert dm["Wealth & Finance"] == 2
        assert dm["Relationships"] == 0

        # 3 active dimensions -> breadth = min(3/3*2, 2) = 2
        active = len([d for d in dm if dm[d] > 0])
        assert active == 3


class TestComputeVaultActivity:
    """Vault nodes indexed today count as modified; those with type != '' as created."""

    def test_compute_vault_activity(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_vault_node(conn, "Daily Notes/today.md", "today", file_type="journal",
                           indexed_at=_ts(TODAY))
        _insert_vault_node(conn, "Concepts/Test.md", "Test", file_type="concept",
                           indexed_at=_ts(TODAY))
        _insert_vault_node(conn, "plain.md", "plain", file_type="",
                           indexed_at=_ts(TODAY))
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)

        assert metrics["vault_files_modified"] == 3
        # Only files with type != '' count as "created"
        assert metrics["vault_files_created"] == 2


class TestEngagementScoreMax:
    """Engagement score cannot exceed 10 regardless of input."""

    def test_engagement_score_max_10(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Journal -> 2 points
        _insert_journal(conn, TODAY)
        # 10 captures -> max 2 points
        for i in range(10):
            _insert_capture(conn, TODAY)
        # 5 completed actions -> max 2 points
        for i in range(5):
            _insert_action(conn, TODAY, status="completed",
                            completed_at=_ts(TODAY))
        # 4 dimensions -> max 2 points
        _insert_capture(conn, TODAY,
                        dims_json=json.dumps(["Health & Vitality", "Mind & Growth",
                                               "Relationships", "Wealth & Finance"]))
        # 10 vault files -> max 2 points
        for i in range(10):
            _insert_vault_node(conn, f"file{i}.md", f"file{i}",
                               file_type="concept", indexed_at=_ts(TODAY))
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)
        assert metrics["engagement_score"] <= 10.0


class TestSaveDailyMetrics:
    """save_daily_metrics persists a row in engagement_daily."""

    def test_save_daily_metrics(self, test_db):
        metrics = compute_daily_metrics(TODAY, db_path=test_db)
        save_daily_metrics(metrics, db_path=test_db)

        assert _count_rows(test_db, "engagement_daily", f"date = '{TODAY}'") == 1

        # Verify stored values
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM engagement_daily WHERE date = ?", (TODAY,)
        ).fetchone()
        conn.close()

        assert dict(row)["captures_count"] == 0
        assert dict(row)["engagement_score"] == 0.0
        assert dict(row)["computed_at"] is not None


class TestSaveIdempotent:
    """Saving twice for the same date should produce exactly 1 row (REPLACE)."""

    def test_save_idempotent(self, test_db):
        metrics = compute_daily_metrics(TODAY, db_path=test_db)
        save_daily_metrics(metrics, db_path=test_db)
        save_daily_metrics(metrics, db_path=test_db)

        assert _count_rows(test_db, "engagement_daily", f"date = '{TODAY}'") == 1


class TestBackfillEngagement:
    """backfill_engagement processes multiple days."""

    def test_backfill_engagement(self, test_db):
        processed = backfill_engagement(days=3, db_path=test_db)

        # Should process today + 3 days back = 4 days
        assert processed >= 3
        assert _count_rows(test_db, "engagement_daily") >= 3


class TestGetEngagementHistory:
    """get_engagement_history returns rows ordered by date DESC."""

    def test_get_engagement_history(self, test_db):
        # Save metrics for 5 consecutive days
        base = datetime.now().date()
        for i in range(5):
            d = (base - timedelta(days=i)).isoformat()
            metrics = compute_daily_metrics(d, db_path=test_db)
            save_daily_metrics(metrics, db_path=test_db)

        history = get_engagement_history(days=3, db_path=test_db)

        # Should return at most 3 days of data (today, yesterday, 2 days ago)
        assert len(history) <= 4  # days=3 means cutoff 3 days ago, so up to 4 rows
        assert len(history) >= 3

        # Verify DESC ordering
        if len(history) >= 2:
            assert history[0]["date"] >= history[1]["date"]


class TestComputeWithEdges:
    """Edges created today contribute to edges_created metric."""

    def test_compute_with_edges(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Need source/target nodes first
        _insert_vault_node(conn, "a.md", "A", indexed_at=_ts(YESTERDAY))
        _insert_vault_node(conn, "b.md", "B", indexed_at=_ts(YESTERDAY))
        # Get their IDs
        a_id = conn.execute(
            "SELECT id FROM vault_nodes WHERE file_path = 'a.md'"
        ).fetchone()[0]
        b_id = conn.execute(
            "SELECT id FROM vault_nodes WHERE file_path = 'b.md'"
        ).fetchone()[0]
        _insert_vault_edge(conn, a_id, b_id, created_at=_ts(TODAY))
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(TODAY, db_path=test_db)
        assert metrics["edges_created"] == 1


class TestComputeSpecificDate:
    """Passing an explicit date only counts data for that date."""

    def test_compute_specific_date(self, test_db):
        target_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        conn = sqlite3.connect(str(test_db))
        # Insert data for the target date
        _insert_journal(conn, target_date, content="Five days ago entry")
        _insert_capture(conn, target_date)
        # Insert data for today (should NOT appear)
        _insert_journal(conn, TODAY, content="Today entry")
        _insert_capture(conn, TODAY)
        _insert_capture(conn, TODAY)
        conn.commit()
        conn.close()

        metrics = compute_daily_metrics(target_date, db_path=test_db)

        assert metrics["date"] == target_date
        assert metrics["journal_entry_count"] == 1
        assert metrics["captures_count"] == 1

        # Verify today's data is separate
        today_metrics = compute_daily_metrics(TODAY, db_path=test_db)
        assert today_metrics["captures_count"] == 2

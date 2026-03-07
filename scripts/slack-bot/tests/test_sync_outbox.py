"""Tests for core.sync_outbox — transactional outbox for Notion sync."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path & module setup
# ---------------------------------------------------------------------------
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing bot modules (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

from core import sync_outbox  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _count(db_path, table, where=""):
    conn = sqlite3.connect(str(db_path))
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    result = conn.execute(sql).fetchone()[0]
    conn.close()
    return result


def _get_row(db_path, outbox_id):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sync_outbox WHERE id = ?", (outbox_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ===========================================================================
# Tests
# ===========================================================================


class TestEnqueue:
    """Tests for sync_outbox.enqueue()."""

    def test_enqueue_creates_pending_row(self, test_db):
        payload = json.dumps({"desc": "Test action"})
        row_id = _run(sync_outbox.enqueue("action_item", "42", "create", payload, db_path=test_db))

        assert row_id is not None
        row = _get_row(test_db, row_id)
        assert row["entity_type"] == "action_item"
        assert row["entity_id"] == "42"
        assert row["operation"] == "create"
        assert row["status"] == "pending"
        assert row["attempt_count"] == 0
        assert row["payload_json"] == payload

    def test_enqueue_deduplicates_pending(self, test_db):
        payload = json.dumps({"desc": "Test"})
        first_id = _run(sync_outbox.enqueue("action_item", "1", "create", payload, db_path=test_db))
        second_id = _run(sync_outbox.enqueue("action_item", "1", "create", payload, db_path=test_db))

        assert first_id is not None
        assert second_id is None
        assert _count(test_db, "sync_outbox", "entity_id = '1'") == 1

    def test_enqueue_deduplicates_processing(self, test_db):
        payload = json.dumps({"desc": "Test"})
        row_id = _run(sync_outbox.enqueue("action_item", "99", "create", payload, db_path=test_db))

        # Manually set to processing
        conn = sqlite3.connect(str(test_db))
        conn.execute("UPDATE sync_outbox SET status = 'processing' WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()

        # Second enqueue should skip
        second_id = _run(sync_outbox.enqueue("action_item", "99", "create", payload, db_path=test_db))
        assert second_id is None

    def test_enqueue_confirmed_create_becomes_update(self, test_db):
        payload = json.dumps({"desc": "Original"})
        row_id = _run(sync_outbox.enqueue("action_item", "5", "create", payload, db_path=test_db))

        # Confirm it
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "UPDATE sync_outbox SET status = 'confirmed', notion_page_id = 'np-123' WHERE id = ?",
            (row_id,),
        )
        conn.commit()
        conn.close()

        # Re-enqueue as create should create an 'update' row
        new_payload = json.dumps({"desc": "Updated"})
        update_id = _run(sync_outbox.enqueue("action_item", "5", "create", new_payload, db_path=test_db))

        assert update_id is not None
        update_row = _get_row(test_db, update_id)
        assert update_row["operation"] == "update"
        assert update_row["status"] == "pending"

    def test_enqueue_resets_failed(self, test_db):
        payload = json.dumps({"desc": "Fail test"})
        row_id = _run(sync_outbox.enqueue("journal", "d1", "create", payload, db_path=test_db))

        # Mark failed
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "UPDATE sync_outbox SET status = 'failed', attempt_count = 1, "
            "error_message = 'API error' WHERE id = ?",
            (row_id,),
        )
        conn.commit()
        conn.close()

        # Re-enqueue should reset
        new_payload = json.dumps({"desc": "Retry"})
        reset_id = _run(sync_outbox.enqueue("journal", "d1", "create", new_payload, db_path=test_db))

        assert reset_id == row_id
        row = _get_row(test_db, row_id)
        assert row["status"] == "pending"
        assert row["attempt_count"] == 0
        assert row["error_message"] is None
        assert row["payload_json"] == new_payload

    def test_enqueue_different_entity_types_not_deduplicated(self, test_db):
        payload = json.dumps({"x": 1})
        id1 = _run(sync_outbox.enqueue("action_item", "1", "create", payload, db_path=test_db))
        id2 = _run(sync_outbox.enqueue("journal", "1", "create", payload, db_path=test_db))

        assert id1 is not None
        assert id2 is not None
        assert id1 != id2


class TestDequeueBatch:
    """Tests for sync_outbox.dequeue_batch()."""

    def test_dequeue_returns_pending_marks_processing(self, test_db):
        payload = json.dumps({"a": 1})
        _run(sync_outbox.enqueue("action_item", "10", "create", payload, db_path=test_db))
        _run(sync_outbox.enqueue("action_item", "11", "create", payload, db_path=test_db))

        batch = _run(sync_outbox.dequeue_batch(limit=50, db_path=test_db))
        assert len(batch) == 2
        assert all(b["entity_type"] == "action_item" for b in batch)

        # Verify they're now processing in DB
        assert _count(test_db, "sync_outbox", "status = 'processing'") == 2
        assert _count(test_db, "sync_outbox", "status = 'pending'") == 0

    def test_dequeue_respects_limit(self, test_db):
        payload = json.dumps({"x": 1})
        for i in range(5):
            _run(sync_outbox.enqueue("action_item", str(i), "create", payload, db_path=test_db))

        batch = _run(sync_outbox.dequeue_batch(limit=2, db_path=test_db))
        assert len(batch) == 2
        assert _count(test_db, "sync_outbox", "status = 'processing'") == 2
        assert _count(test_db, "sync_outbox", "status = 'pending'") == 3

    def test_dequeue_empty_returns_empty(self, test_db):
        batch = _run(sync_outbox.dequeue_batch(db_path=test_db))
        assert batch == []

    def test_dequeue_skips_non_pending(self, test_db):
        payload = json.dumps({"x": 1})
        _run(sync_outbox.enqueue("action_item", "20", "create", payload, db_path=test_db))

        # Mark confirmed
        conn = sqlite3.connect(str(test_db))
        conn.execute("UPDATE sync_outbox SET status = 'confirmed' WHERE entity_id = '20'")
        conn.commit()
        conn.close()

        batch = _run(sync_outbox.dequeue_batch(db_path=test_db))
        assert batch == []


class TestConfirm:
    """Tests for sync_outbox.confirm()."""

    def test_confirm_sets_status_and_notion_id(self, test_db):
        payload = json.dumps({"desc": "Confirm test"})
        row_id = _run(sync_outbox.enqueue("action_item", "30", "create", payload, db_path=test_db))

        _run(sync_outbox.confirm(row_id, "notion-page-abc", db_path=test_db))

        row = _get_row(test_db, row_id)
        assert row["status"] == "confirmed"
        assert row["notion_page_id"] == "notion-page-abc"
        assert row["confirmed_at"] is not None


class TestFail:
    """Tests for sync_outbox.fail()."""

    def test_fail_retries_under_max(self, test_db):
        payload = json.dumps({"desc": "Fail retry"})
        row_id = _run(sync_outbox.enqueue("action_item", "40", "create", payload, db_path=test_db))

        _run(sync_outbox.fail(row_id, "Timeout error", db_path=test_db))

        row = _get_row(test_db, row_id)
        assert row["status"] == "pending"  # back to pending for retry
        assert row["attempt_count"] == 1
        assert row["error_message"] == "Timeout error"

    def test_fail_dead_letters_at_max(self, test_db):
        payload = json.dumps({"desc": "Dead letter"})
        row_id = _run(sync_outbox.enqueue("action_item", "41", "create", payload, db_path=test_db))

        # Fail 3 times (max_attempts defaults to 3)
        _run(sync_outbox.fail(row_id, "Error 1", db_path=test_db))
        _run(sync_outbox.fail(row_id, "Error 2", db_path=test_db))
        _run(sync_outbox.fail(row_id, "Error 3", db_path=test_db))

        row = _get_row(test_db, row_id)
        assert row["status"] == "dead_letter"
        assert row["attempt_count"] == 3
        assert row["error_message"] == "Error 3"

    def test_fail_increments_progressively(self, test_db):
        payload = json.dumps({"desc": "Progressive"})
        row_id = _run(sync_outbox.enqueue("action_item", "42", "create", payload, db_path=test_db))

        # First failure -> pending (attempt 1 of 3)
        _run(sync_outbox.fail(row_id, "Err1", db_path=test_db))
        row = _get_row(test_db, row_id)
        assert row["status"] == "pending"
        assert row["attempt_count"] == 1

        # Second failure -> pending (attempt 2 of 3)
        _run(sync_outbox.fail(row_id, "Err2", db_path=test_db))
        row = _get_row(test_db, row_id)
        assert row["status"] == "pending"
        assert row["attempt_count"] == 2

        # Third failure -> dead_letter (attempt 3 of 3)
        _run(sync_outbox.fail(row_id, "Err3", db_path=test_db))
        row = _get_row(test_db, row_id)
        assert row["status"] == "dead_letter"
        assert row["attempt_count"] == 3


class TestSweepStale:
    """Tests for sync_outbox.sweep_stale()."""

    def test_sweep_resets_stuck_processing(self, test_db):
        payload = json.dumps({"desc": "Stale"})
        row_id = _run(sync_outbox.enqueue("action_item", "50", "create", payload, db_path=test_db))

        # Simulate stuck: set processing_at to 20 minutes ago
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "UPDATE sync_outbox SET status = 'processing', "
            "processing_at = datetime('now', '-20 minutes') WHERE id = ?",
            (row_id,),
        )
        conn.commit()
        conn.close()

        swept = _run(sync_outbox.sweep_stale(timeout_minutes=10, db_path=test_db))
        assert swept == 1

        row = _get_row(test_db, row_id)
        assert row["status"] == "pending"
        assert row["processing_at"] is None

    def test_sweep_leaves_recent_processing_alone(self, test_db):
        payload = json.dumps({"desc": "Recent"})
        row_id = _run(sync_outbox.enqueue("action_item", "51", "create", payload, db_path=test_db))

        # Set processing_at to now (not stale)
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "UPDATE sync_outbox SET status = 'processing', "
            "processing_at = datetime('now') WHERE id = ?",
            (row_id,),
        )
        conn.commit()
        conn.close()

        swept = _run(sync_outbox.sweep_stale(timeout_minutes=10, db_path=test_db))
        assert swept == 0

        row = _get_row(test_db, row_id)
        assert row["status"] == "processing"


class TestLifecycle:
    """End-to-end lifecycle tests."""

    def test_enqueue_dequeue_confirm(self, test_db):
        """Full happy path: enqueue -> dequeue -> confirm."""
        payload = json.dumps({"description": "Buy groceries", "icor": "Health"})
        row_id = _run(sync_outbox.enqueue("action_item", "100", "create", payload, db_path=test_db))
        assert row_id is not None

        # Dequeue
        batch = _run(sync_outbox.dequeue_batch(db_path=test_db))
        assert len(batch) == 1
        item = batch[0]
        assert item["id"] == row_id
        assert item["entity_type"] == "action_item"

        # Confirm
        _run(sync_outbox.confirm(row_id, "notion-page-xyz", db_path=test_db))
        row = _get_row(test_db, row_id)
        assert row["status"] == "confirmed"
        assert row["notion_page_id"] == "notion-page-xyz"

        # Dequeue again should be empty
        batch2 = _run(sync_outbox.dequeue_batch(db_path=test_db))
        assert batch2 == []

    def test_enqueue_dequeue_fail_retry_confirm(self, test_db):
        """Retry path: enqueue -> dequeue -> fail -> dequeue (retry) -> confirm."""
        payload = json.dumps({"date": "2026-03-07", "summary": "Good day"})
        row_id = _run(sync_outbox.enqueue("journal", "2026-03-07", "create", payload, db_path=test_db))

        # First attempt: dequeue + fail
        batch = _run(sync_outbox.dequeue_batch(db_path=test_db))
        assert len(batch) == 1
        _run(sync_outbox.fail(row_id, "API timeout", db_path=test_db))

        # Row should be back to pending
        row = _get_row(test_db, row_id)
        assert row["status"] == "pending"
        assert row["attempt_count"] == 1

        # Second attempt: dequeue + confirm
        batch2 = _run(sync_outbox.dequeue_batch(db_path=test_db))
        assert len(batch2) == 1
        assert batch2[0]["id"] == row_id
        _run(sync_outbox.confirm(row_id, "notion-journal-123", db_path=test_db))

        row = _get_row(test_db, row_id)
        assert row["status"] == "confirmed"
        assert row["notion_page_id"] == "notion-journal-123"

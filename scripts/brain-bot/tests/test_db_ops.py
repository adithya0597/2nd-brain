"""Tests for core/db_ops.py — Async SQLite operations."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing db_ops
sys.modules.setdefault("config", MagicMock())

from core.db_ops import (
    query,
    execute,
    get_pending_actions,
    insert_action_item,
    get_neglected_elements,
    update_sync_state,
    get_sync_state,
    get_icor_hierarchy,
    log_sync_operation,
    get_unpushed_actions,
    update_action_external,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(test_db):
    """Alias for the test_db fixture from conftest."""
    return test_db


# ---------------------------------------------------------------------------
# Generic query / execute
# ---------------------------------------------------------------------------

class TestGenericOps:

    @pytest.mark.asyncio
    async def test_query_returns_list_of_dicts(self, db_path):
        rows = await query(
            "SELECT id, level, name FROM icor_hierarchy WHERE level = 'dimension' ORDER BY id",
            db_path=db_path,
        )
        assert isinstance(rows, list)
        assert len(rows) == 6
        assert isinstance(rows[0], dict)
        assert "id" in rows[0]
        assert "level" in rows[0]
        assert "name" in rows[0]
        assert rows[0]["name"] == "Health & Vitality"

    @pytest.mark.asyncio
    async def test_query_with_params(self, db_path):
        rows = await query(
            "SELECT name FROM icor_hierarchy WHERE level = ? AND parent_id = ?",
            ("key_element", 1),
            db_path=db_path,
        )
        names = [r["name"] for r in rows]
        assert "Fitness" in names
        assert "Nutrition" in names

    @pytest.mark.asyncio
    async def test_query_empty_result(self, db_path):
        rows = await query(
            "SELECT * FROM action_items WHERE id = -1",
            db_path=db_path,
        )
        assert rows == []

    @pytest.mark.asyncio
    async def test_execute_returns_lastrowid(self, db_path):
        rowid = await execute(
            "INSERT INTO action_items (description, source_file, status) VALUES (?, ?, 'pending')",
            ("Test action", "test.md"),
            db_path=db_path,
        )
        assert isinstance(rowid, int)
        assert rowid > 0

    @pytest.mark.asyncio
    async def test_execute_update(self, db_path):
        # Insert first
        rowid = await execute(
            "INSERT INTO action_items (description, source_file, status) VALUES (?, ?, 'pending')",
            ("To be updated", "test.md"),
            db_path=db_path,
        )
        # Update
        await execute(
            "UPDATE action_items SET status = 'completed' WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        rows = await query(
            "SELECT status FROM action_items WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert rows[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# insert_action_item
# ---------------------------------------------------------------------------

class TestInsertActionItem:

    @pytest.mark.asyncio
    async def test_creates_pending_action(self, db_path):
        rowid = await insert_action_item(
            description="Call the dentist",
            source="slack",
            icor_element="Health & Vitality",
            db_path=db_path,
        )
        assert rowid > 0

        rows = await query(
            "SELECT description, status, icor_element FROM action_items WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert len(rows) == 1
        assert rows[0]["description"] == "Call the dentist"
        assert rows[0]["status"] == "pending"
        assert rows[0]["icor_element"] == "Health & Vitality"

    @pytest.mark.asyncio
    async def test_action_with_project(self, db_path):
        rowid = await insert_action_item(
            description="Review PR",
            source="slack",
            icor_element="Systems & Environment",
            icor_project="Second Brain Bot",
            db_path=db_path,
        )
        rows = await query(
            "SELECT icor_project FROM action_items WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert rows[0]["icor_project"] == "Second Brain Bot"

    @pytest.mark.asyncio
    async def test_action_without_optional_fields(self, db_path):
        rowid = await insert_action_item(
            description="Some task",
            source="test",
            db_path=db_path,
        )
        rows = await query(
            "SELECT icor_element, icor_project FROM action_items WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert rows[0]["icor_element"] is None
        assert rows[0]["icor_project"] is None


# ---------------------------------------------------------------------------
# get_pending_actions
# ---------------------------------------------------------------------------

class TestGetPendingActions:

    @pytest.mark.asyncio
    async def test_returns_only_pending(self, db_path):
        # Insert pending
        await insert_action_item("Pending task", "test", db_path=db_path)
        # Insert completed
        await execute(
            "INSERT INTO action_items (description, source_file, status) VALUES (?, ?, 'completed')",
            ("Completed task", "test"),
            db_path=db_path,
        )

        pending = await get_pending_actions(db_path=db_path)
        assert len(pending) == 1
        assert pending[0]["description"] == "Pending task"

    @pytest.mark.asyncio
    async def test_empty_when_no_pending(self, db_path):
        pending = await get_pending_actions(db_path=db_path)
        assert pending == []

    @pytest.mark.asyncio
    async def test_returns_expected_columns(self, db_path):
        await insert_action_item("Test", "test", "Health & Vitality", "ProjectX", db_path=db_path)
        pending = await get_pending_actions(db_path=db_path)
        assert len(pending) == 1
        row = pending[0]
        assert "id" in row
        assert "description" in row
        assert "source_file" in row
        assert "icor_element" in row
        assert "icor_project" in row


# ---------------------------------------------------------------------------
# get_neglected_elements
# ---------------------------------------------------------------------------

class TestGetNeglectedElements:

    @pytest.mark.asyncio
    async def test_elements_with_null_last_mentioned(self, db_path):
        """Key elements with NULL last_mentioned should appear as neglected."""
        neglected = await get_neglected_elements(days=7, db_path=db_path)
        # Our seed data has key elements with NULL last_mentioned
        assert len(neglected) > 0
        for item in neglected:
            assert item["last_mentioned"] is None or item["days_since"] is not None

    @pytest.mark.asyncio
    async def test_recently_mentioned_excluded(self, db_path):
        # Update a key element to have been mentioned today
        await execute(
            "UPDATE icor_hierarchy SET last_mentioned = date('now') WHERE id = 101",
            db_path=db_path,
        )
        neglected = await get_neglected_elements(days=7, db_path=db_path)
        neglected_ids = [n["id"] for n in neglected]
        assert 101 not in neglected_ids


# ---------------------------------------------------------------------------
# Sync state operations
# ---------------------------------------------------------------------------

class TestSyncState:

    @pytest.mark.asyncio
    async def test_get_sync_state(self, db_path):
        state = await get_sync_state("tasks", db_path=db_path)
        assert state is not None
        assert state["entity_type"] == "tasks"
        assert state["last_synced_at"] is None
        assert state["items_synced"] == 0

    @pytest.mark.asyncio
    async def test_get_sync_state_nonexistent(self, db_path):
        state = await get_sync_state("nonexistent_type", db_path=db_path)
        assert state is None

    @pytest.mark.asyncio
    async def test_update_sync_state(self, db_path):
        await update_sync_state(
            entity_type="tasks",
            last_synced_at="2026-03-06T12:00:00",
            items_synced=42,
            direction="push",
            db_path=db_path,
        )

        state = await get_sync_state("tasks", db_path=db_path)
        assert state["last_synced_at"] == "2026-03-06T12:00:00"
        assert state["items_synced"] == 42
        assert state["last_sync_direction"] == "push"

    @pytest.mark.asyncio
    async def test_update_sync_state_pull(self, db_path):
        await update_sync_state(
            entity_type="projects",
            last_synced_at="2026-03-06T18:00:00",
            items_synced=5,
            direction="pull",
            db_path=db_path,
        )
        state = await get_sync_state("projects", db_path=db_path)
        assert state["last_sync_direction"] == "pull"


# ---------------------------------------------------------------------------
# get_icor_hierarchy
# ---------------------------------------------------------------------------

class TestGetICORHierarchy:

    @pytest.mark.asyncio
    async def test_returns_full_hierarchy(self, db_path):
        rows = await get_icor_hierarchy(db_path=db_path)
        assert len(rows) >= 10  # 6 dimensions + 4 key elements from seed
        dimensions = [r for r in rows if r["parent_name"] is None]
        key_elements = [r for r in rows if r["parent_name"] is not None]
        assert len(dimensions) == 6
        assert len(key_elements) >= 4


# ---------------------------------------------------------------------------
# log_sync_operation
# ---------------------------------------------------------------------------

class TestLogSyncOperation:

    @pytest.mark.asyncio
    async def test_log_sync_success(self, db_path):
        rowid = await log_sync_operation(
            operation="push_task",
            source_file="action_1",
            target="notion_page_abc",
            status="success",
            details="Pushed successfully",
            db_path=db_path,
        )
        assert rowid > 0

        rows = await query(
            "SELECT operation, status, details FROM vault_sync_log WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert rows[0]["operation"] == "push_task"
        assert rows[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_log_sync_failure(self, db_path):
        rowid = await log_sync_operation(
            operation="pull_project",
            source_file="project_1",
            target="local_db",
            status="failed",
            details="Connection timeout",
            db_path=db_path,
        )
        rows = await query(
            "SELECT status, details FROM vault_sync_log WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert rows[0]["status"] == "failed"
        assert "timeout" in rows[0]["details"].lower()


# ---------------------------------------------------------------------------
# get_unpushed_actions and update_action_external
# ---------------------------------------------------------------------------

class TestUnpushedActions:

    @pytest.mark.asyncio
    async def test_unpushed_returns_items_without_external_id(self, db_path):
        await insert_action_item("Unpushed task", "test", db_path=db_path)
        unpushed = await get_unpushed_actions(db_path=db_path)
        assert len(unpushed) == 1
        assert unpushed[0]["description"] == "Unpushed task"

    @pytest.mark.asyncio
    async def test_pushed_items_excluded(self, db_path):
        rowid = await insert_action_item("Will be pushed", "test", db_path=db_path)
        await update_action_external(rowid, "notion_page_123", db_path=db_path)
        unpushed = await get_unpushed_actions(db_path=db_path)
        assert len(unpushed) == 0

    @pytest.mark.asyncio
    async def test_update_action_external(self, db_path):
        rowid = await insert_action_item("Task to push", "test", db_path=db_path)
        await update_action_external(rowid, "notion_page_xyz", db_path=db_path)

        rows = await query(
            "SELECT external_id, external_system FROM action_items WHERE id = ?",
            (rowid,),
            db_path=db_path,
        )
        assert rows[0]["external_id"] == "notion_page_xyz"
        assert rows[0]["external_system"] == "notion_tasks"

"""Tests for core/notion_sync.py — Journal sync idempotency and sync state."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing
_mock_config = MagicMock()
_mock_config.DB_PATH = Path("/dev/null")
sys.modules.setdefault("config", _mock_config)

from core.notion_sync import NotionSync, SyncResult, RegistryManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_notion_client():
    """Create a mock NotionClientWrapper."""
    client = AsyncMock()
    client.create_page = AsyncMock(return_value={"id": "page-id-123"})
    client.get_page = AsyncMock(return_value={"id": "page-id-123"})
    client.query_database = AsyncMock(return_value=[])
    return client


@pytest.fixture()
def registry_path(tmp_path):
    """Create a temp registry file."""
    path = tmp_path / "notion-registry.json"
    path.write_text('{"dimensions": {}, "key_elements": {}, "goals": {}, "projects": {}}')
    return path


@pytest.fixture()
def vault_path(tmp_path):
    """Create a temp vault directory."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Identity").mkdir()
    (vault / "Projects").mkdir()
    (vault / "Goals").mkdir()
    (vault / "People").mkdir()
    return vault


@pytest.fixture()
def collection_ids():
    return {
        "tasks": "collection://test-tasks-id",
        "projects": "collection://test-projects-id",
        "goals": "collection://test-goals-id",
        "tags": "collection://test-tags-id",
        "notes": "collection://test-notes-id",
        "people": "collection://test-people-id",
    }


@pytest.fixture()
def sync_instance(mock_notion_client, registry_path, test_db, vault_path, collection_ids):
    """Create a NotionSync instance with test dependencies."""
    return NotionSync(
        client=mock_notion_client,
        registry_path=registry_path,
        db_path=test_db,
        vault_path=vault_path,
        collection_ids=collection_ids,
    )


# ---------------------------------------------------------------------------
# _push_journal_entries — Idempotency tests
# ---------------------------------------------------------------------------

class TestPushJournalEntries:

    @pytest.mark.asyncio
    async def test_enqueues_to_outbox_before_create_page(self, sync_instance, test_db):
        """Entries should be enqueued to the outbox before Notion create_page."""
        call_order = []

        async def mock_enqueue(*args, **kwargs):
            call_order.append("enqueue")
            return 1

        async def mock_dequeue(*args, **kwargs):
            call_order.append("dequeue")
            return [{"id": 1, "entity_type": "journal", "entity_id": "2026-03-01",
                     "operation": "create",
                     "payload_json": '{"date": "2026-03-01", "summary": "Test entry"}',
                     "attempt_count": 0, "max_attempts": 3}]

        async def mock_confirm(*args, **kwargs):
            call_order.append("confirm")

        async def mock_create_page(**kwargs):
            call_order.append("create_page")
            return {"id": "new-page-id"}

        entries = [{"date": "2026-03-01", "summary": "Test entry", "content": "content"}]

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.sync_outbox.enqueue", side_effect=mock_enqueue), \
             patch("core.notion_sync.sync_outbox.dequeue_batch", side_effect=mock_dequeue), \
             patch("core.notion_sync.sync_outbox.confirm", side_effect=mock_confirm), \
             patch("core.notion_sync.db_ops.log_sync_operation", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = mock_create_page
            await sync_instance._push_journal_entries()

        assert call_order == ["enqueue", "dequeue", "create_page", "confirm"]

    @pytest.mark.asyncio
    async def test_calls_outbox_fail_on_create_page_failure(self, sync_instance):
        """On create_page failure, sync_outbox.fail should be called."""
        mock_fail = AsyncMock()

        entries = [{"date": "2026-03-01", "summary": "Test entry", "content": "content"}]

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.sync_outbox.enqueue", AsyncMock(return_value=1)), \
             patch("core.notion_sync.sync_outbox.dequeue_batch", AsyncMock(return_value=[
                 {"id": 1, "entity_type": "journal", "entity_id": "2026-03-01",
                  "operation": "create",
                  "payload_json": '{"date": "2026-03-01", "summary": "Test entry"}',
                  "attempt_count": 0, "max_attempts": 3}
             ])), \
             patch("core.notion_sync.sync_outbox.fail", mock_fail), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = AsyncMock(side_effect=Exception("Notion API error"))
            await sync_instance._push_journal_entries()

        mock_fail.assert_called_once()
        assert mock_fail.call_args[0][0] == 1  # outbox_id
        assert "Notion API error" in mock_fail.call_args[0][1]  # error_message

    @pytest.mark.asyncio
    async def test_update_sync_state_called_when_notes_pushed(self, sync_instance):
        """update_sync_state should be called when notes_pushed > 0."""
        entries = [{"date": "2026-03-01", "summary": "Test", "content": "content"}]
        mock_update = AsyncMock()

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.log_sync_operation", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", mock_update), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = AsyncMock(return_value={"id": "page-123"})
            await sync_instance._push_journal_entries()

        mock_update.assert_called_once()
        call_args = mock_update.call_args
        assert call_args[0][0] == "notes"  # entity_type
        assert call_args[0][2] == 1  # items_synced
        assert call_args[0][3] == "push"  # direction

    @pytest.mark.asyncio
    async def test_update_sync_state_NOT_called_when_no_notes_pushed(self, sync_instance):
        """update_sync_state should NOT be called when notes_pushed == 0."""
        entries = [{"date": "2026-03-01", "summary": "Test", "content": "content"}]
        mock_update = AsyncMock()

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.log_sync_operation", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", mock_update), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            # All entries fail
            sync_instance._client.create_page = AsyncMock(side_effect=Exception("fail"))
            await sync_instance._push_journal_entries()

        mock_update.assert_not_called()
        assert sync_instance._result.notes_pushed == 0

    @pytest.mark.asyncio
    async def test_update_sync_state_not_called_when_no_entries(self, sync_instance):
        """update_sync_state should NOT be called when there are no unsynced entries."""
        mock_update = AsyncMock()

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=[])), \
             patch("core.notion_sync.db_ops.update_sync_state", mock_update):
            await sync_instance._push_journal_entries()

        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_failure_handles_correctly(self, sync_instance):
        """When some entries succeed and some fail, counts and state are correct."""
        entries = [
            {"date": "2026-03-01", "summary": "Entry 1", "content": "c1"},
            {"date": "2026-03-02", "summary": "Entry 2", "content": "c2"},
            {"date": "2026-03-03", "summary": "Entry 3", "content": "c3"},
        ]

        call_count = {"n": 0}

        async def mock_create_page(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise Exception("Notion API error for entry 2")
            return {"id": f"page-{call_count['n']}"}

        mock_update = AsyncMock()

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.log_sync_operation", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", mock_update), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = mock_create_page
            await sync_instance._push_journal_entries()

        # 2 succeeded, 1 failed
        assert sync_instance._result.notes_pushed == 2
        assert len(sync_instance._result.warnings) == 1
        # update_sync_state should be called since notes_pushed > 0
        mock_update.assert_called_once()
        assert mock_update.call_args[0][2] == 2  # items_synced = 2

    @pytest.mark.asyncio
    async def test_notes_pushed_count_increments_correctly(self, sync_instance):
        """notes_pushed should increment for each successful push."""
        entries = [
            {"date": "2026-03-01", "summary": "A", "content": "c1"},
            {"date": "2026-03-02", "summary": "B", "content": "c2"},
        ]

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.log_sync_operation", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = AsyncMock(return_value={"id": "page-x"})
            await sync_instance._push_journal_entries()

        assert sync_instance._result.notes_pushed == 2

    @pytest.mark.asyncio
    async def test_warning_added_on_create_page_failure(self, sync_instance):
        """A warning should be appended to result.warnings on failure."""
        entries = [{"date": "2026-03-01", "summary": "Test", "content": "c"}]

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = AsyncMock(side_effect=Exception("Notion 500"))
            await sync_instance._push_journal_entries()

        assert len(sync_instance._result.warnings) == 1
        assert "2026-03-01" in sync_instance._result.warnings[0]

    @pytest.mark.asyncio
    async def test_log_sync_operation_called_on_success(self, sync_instance):
        """log_sync_operation should be called for each successful push."""
        entries = [{"date": "2026-03-01", "summary": "Summary text", "content": "c"}]
        mock_log = AsyncMock()

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.log_sync_operation", mock_log), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            sync_instance._client.create_page = AsyncMock(return_value={"id": "page-1"})
            await sync_instance._push_journal_entries()

        mock_log.assert_called_once()
        call_args = mock_log.call_args[0]
        assert call_args[0] == "push_journal"
        assert call_args[1] == "2026-03-01"
        assert call_args[2] == "notion_notes"
        assert call_args[3] == "success"


# ---------------------------------------------------------------------------
# _push_action_items — Idempotency tests
# ---------------------------------------------------------------------------

class TestPushActionItems:

    @pytest.mark.asyncio
    async def test_enqueues_to_outbox_before_create(self, sync_instance):
        """Actions should be enqueued to outbox before Notion create_page."""
        call_order = []

        async def mock_enqueue(*args, **kwargs):
            call_order.append("enqueue")
            return 1

        async def mock_dequeue(*args, **kwargs):
            call_order.append("dequeue")
            return [{"id": 1, "entity_type": "action_item", "entity_id": "1",
                     "operation": "create",
                     "payload_json": '{"id": 1, "description": "Do thing", "status": "pending"}',
                     "attempt_count": 0, "max_attempts": 3}]

        async def mock_confirm(*args, **kwargs):
            call_order.append("confirm")

        async def mock_create_page(**kwargs):
            call_order.append("create_page")
            return {"id": "new-task-id"}

        actions = [{"id": 1, "description": "Do thing", "status": "pending"}]

        with patch("core.notion_sync.db_ops.get_unpushed_actions", AsyncMock(return_value=actions)), \
             patch("core.notion_sync.sync_outbox.enqueue", side_effect=mock_enqueue), \
             patch("core.notion_sync.sync_outbox.dequeue_batch", side_effect=mock_dequeue), \
             patch("core.notion_sync.sync_outbox.confirm", side_effect=mock_confirm), \
             patch("core.notion_sync.db_ops.update_action_external", AsyncMock()), \
             patch("core.notion_sync.db_ops.log_sync_operation", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.action_to_notion_task", return_value={}):
            sync_instance._client.create_page = mock_create_page
            await sync_instance._push_action_items()

        assert call_order == ["enqueue", "dequeue", "create_page", "confirm"]

    @pytest.mark.asyncio
    async def test_calls_outbox_fail_on_action_failure(self, sync_instance):
        """On action push failure, sync_outbox.fail should be called."""
        mock_fail = AsyncMock()

        actions = [{"id": 1, "description": "Do thing", "status": "pending"}]

        with patch("core.notion_sync.db_ops.get_unpushed_actions", AsyncMock(return_value=actions)), \
             patch("core.notion_sync.sync_outbox.enqueue", AsyncMock(return_value=1)), \
             patch("core.notion_sync.sync_outbox.dequeue_batch", AsyncMock(return_value=[
                 {"id": 1, "entity_type": "action_item", "entity_id": "1",
                  "operation": "create",
                  "payload_json": '{"id": 1, "description": "Do thing", "status": "pending"}',
                  "attempt_count": 0, "max_attempts": 3}
             ])), \
             patch("core.notion_sync.sync_outbox.fail", mock_fail), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.action_to_notion_task", return_value={}):
            sync_instance._client.create_page = AsyncMock(side_effect=Exception("fail"))
            await sync_instance._push_action_items()

        mock_fail.assert_called_once()
        assert mock_fail.call_args[0][0] == 1  # outbox_id


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------

class TestSyncResult:

    def test_summary_with_notes_pushed(self):
        result = SyncResult(notes_pushed=3)
        summary = result.summary()
        assert "Journal notes pushed: 3" in summary

    def test_summary_with_no_changes(self):
        result = SyncResult()
        summary = result.summary()
        assert "No changes needed" in summary

    def test_summary_with_errors(self):
        result = SyncResult(errors=["Error 1", "Error 2"])
        summary = result.summary()
        assert "Errors: 2" in summary

    def test_summary_with_multiple_fields(self):
        result = SyncResult(tasks_pushed=2, projects_pulled=5, tags_synced=3)
        summary = result.summary()
        assert "Tasks pushed: 2" in summary
        assert "Projects pulled: 5" in summary
        assert "Tags synced: 3" in summary


# ---------------------------------------------------------------------------
# RegistryManager
# ---------------------------------------------------------------------------

class TestRegistryManager:

    def test_load_creates_default_structure(self, tmp_path):
        path = tmp_path / "registry.json"
        rm = RegistryManager(path)
        data = rm.load()
        assert "dimensions" in data
        assert "key_elements" in data
        assert "goals" in data
        assert "projects" in data

    def test_save_and_reload(self, tmp_path):
        path = tmp_path / "registry.json"
        rm = RegistryManager(path)
        rm.load()
        rm.set_tag("Health & Vitality", "page-1", "dimension")
        rm.save()

        rm2 = RegistryManager(path)
        data = rm2.load()
        assert data["dimensions"]["Health & Vitality"]["notion_page_id"] == "page-1"

    def test_get_tag_notion_id_dimension(self, tmp_path):
        path = tmp_path / "registry.json"
        rm = RegistryManager(path)
        rm.load()
        rm.set_tag("Health & Vitality", "page-1", "dimension")
        assert rm.get_tag_notion_id("Health & Vitality") == "page-1"

    def test_get_tag_notion_id_key_element(self, tmp_path):
        path = tmp_path / "registry.json"
        rm = RegistryManager(path)
        rm.load()
        rm.set_tag("Fitness", "page-2", "key_element", dimension="Health & Vitality")
        assert rm.get_tag_notion_id("Fitness") == "page-2"

    def test_get_tag_notion_id_not_found(self, tmp_path):
        path = tmp_path / "registry.json"
        rm = RegistryManager(path)
        rm.load()
        assert rm.get_tag_notion_id("Nonexistent") is None


# ---------------------------------------------------------------------------
# Dry-run mode tests
# ---------------------------------------------------------------------------

class TestDryRunMode:

    def test_dry_run_defaults_false(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
        )
        assert syncer._dry_run is False

    def test_dry_run_can_be_enabled(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        assert syncer._dry_run is True

    @pytest.mark.asyncio
    async def test_dry_run_skips_tag_create_page(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """In dry-run, create_page should never be called for tags."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        elements = [{"id": 1, "name": "Test Dim", "level": "dimension", "parent_id": None}]

        with patch("core.notion_sync.db_ops.get_icor_without_notion_id", AsyncMock(return_value=elements)), \
             patch("core.notion_sync.db_ops.get_icor_hierarchy", AsyncMock(return_value=[])), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.icor_element_to_notion_tag", return_value={}):
            await syncer._sync_icor_tags()

        mock_notion_client.create_page.assert_not_called()
        assert syncer._result.tags_synced == 1
        assert len(syncer._result.dry_run_actions) == 1
        assert "Would push tag" in syncer._result.dry_run_actions[0]

    @pytest.mark.asyncio
    async def test_dry_run_skips_action_create_page(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """In dry-run, create_page should never be called for actions."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        actions = [{"id": 1, "description": "Test action", "status": "pending"}]

        with patch("core.notion_sync.db_ops.get_unpushed_actions", AsyncMock(return_value=actions)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.action_to_notion_task", return_value={}):
            await syncer._push_action_items()

        mock_notion_client.create_page.assert_not_called()
        assert syncer._result.tasks_pushed == 1
        assert "Would push action" in syncer._result.dry_run_actions[0]

    @pytest.mark.asyncio
    async def test_dry_run_skips_journal_create_page(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """In dry-run, create_page should never be called for journal entries."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        entries = [{"date": "2026-03-01", "summary": "Test", "content": "c"}]

        with patch("core.notion_sync.db_ops.get_unsynced_journal_entries", AsyncMock(return_value=entries)), \
             patch("core.notion_sync.db_ops.execute", AsyncMock()), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.journal_to_notion_note", return_value={}):
            await syncer._push_journal_entries()

        mock_notion_client.create_page.assert_not_called()
        assert syncer._result.notes_pushed == 1
        assert "Would push journal" in syncer._result.dry_run_actions[0]

    @pytest.mark.asyncio
    async def test_dry_run_skips_concept_create_page(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """In dry-run, create_page should never be called for concepts."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        concepts = [{"id": 1, "name": "Test Concept", "status": "seedling"}]

        with patch("core.notion_sync.db_ops.get_unsynced_concepts", AsyncMock(return_value=concepts)), \
             patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()), \
             patch("core.notion_sync.concept_to_notion_note", return_value={}):
            await syncer._push_concepts()

        mock_notion_client.create_page.assert_not_called()
        assert syncer._result.concepts_pushed == 1
        assert "Would push concept" in syncer._result.dry_run_actions[0]

    @pytest.mark.asyncio
    async def test_dry_run_pull_methods_unaffected(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """Pull methods should still work normally in dry-run."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        # query_database should still be called for pulls
        mock_notion_client.query_database = AsyncMock(return_value=[])

        with patch("core.notion_sync.db_ops.update_sync_state", AsyncMock()):
            await syncer._pull_projects()

        mock_notion_client.query_database.assert_called_once()

    @pytest.mark.asyncio
    async def test_dry_run_skips_vault_writes(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """In dry-run, run_full_sync should skip vault file writes and registry save."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        syncer._registry.load()

        with patch.object(syncer, '_sync_icor_tags', AsyncMock()), \
             patch.object(syncer, '_push_action_items', AsyncMock()), \
             patch.object(syncer, '_pull_task_status', AsyncMock()), \
             patch.object(syncer, '_pull_projects', AsyncMock()), \
             patch.object(syncer, '_pull_goals', AsyncMock()), \
             patch.object(syncer, '_push_journal_entries', AsyncMock()), \
             patch.object(syncer, '_push_concepts', AsyncMock()), \
             patch.object(syncer, '_sync_people', AsyncMock()), \
             patch.object(syncer, '_update_vault_files', AsyncMock()) as mock_vault, \
             patch.object(syncer._registry, 'save') as mock_save, \
             patch.object(syncer, '_log_sync_operations', AsyncMock()):
            result = await syncer.run_full_sync()

        mock_vault.assert_not_called()
        mock_save.assert_not_called()
        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_dry_run_selective_sync_skips_registry_save(self, mock_notion_client, registry_path, test_db, vault_path, collection_ids):
        """In dry-run selective sync, registry save should be skipped."""
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )
        syncer._registry.load()

        with patch.object(syncer, '_push_action_items', AsyncMock()), \
             patch.object(syncer._registry, 'save') as mock_save:
            result = await syncer.run_selective_sync(["tasks"])

        mock_save.assert_not_called()
        assert result.dry_run is True


class TestSyncResultDryRun:

    def test_summary_shows_dry_run_header(self):
        result = SyncResult(dry_run=True, tasks_pushed=2)
        summary = result.summary()
        assert summary.startswith("DRY RUN")
        assert "Tasks pushed: 2" in summary

    def test_summary_shows_simulated_actions_count(self):
        result = SyncResult(
            dry_run=True,
            dry_run_actions=["Would push tag: X", "Would push tag: Y"],
        )
        summary = result.summary()
        assert "Simulated actions: 2" in summary

    def test_summary_normal_mode_no_dry_run_header(self):
        result = SyncResult(tasks_pushed=2)
        summary = result.summary()
        assert not summary.startswith("DRY RUN")

    def test_dry_run_defaults(self):
        result = SyncResult()
        assert result.dry_run is False
        assert result.dry_run_actions == []

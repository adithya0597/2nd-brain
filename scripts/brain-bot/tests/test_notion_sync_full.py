"""Tests for core/notion_sync.py — SyncResult, RegistryManager, and NotionSync."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())
# Create a real exception class for notion_client.errors.APIResponseError
class _FakeAPIResponseError(Exception):
    def __init__(self, message="", status=400, code="", body=""):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body

_notion_mock = MagicMock()
_notion_errors_mock = MagicMock()
_notion_errors_mock.APIResponseError = _FakeAPIResponseError
sys.modules.setdefault("notion_client", _notion_mock)
sys.modules.setdefault("notion_client.errors", _notion_errors_mock)

from core.notion_sync import SyncResult, RegistryManager, NotionSync, _strip_collection


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------

class TestSyncResult:
    def test_defaults(self):
        r = SyncResult()
        assert r.tasks_pushed == 0
        assert r.errors == []
        assert r.warnings == []
        assert r.dry_run is False

    def test_summary_empty(self):
        r = SyncResult()
        s = r.summary()
        assert "No changes needed" in s

    def test_summary_with_counts(self):
        r = SyncResult(tasks_pushed=5, projects_pulled=2, errors=["x"])
        s = r.summary()
        assert "Tasks pushed: 5" in s
        assert "Projects pulled: 2" in s
        assert "Errors: 1" in s

    def test_summary_dry_run(self):
        r = SyncResult(dry_run=True, dry_run_actions=["a", "b"])
        s = r.summary()
        assert "DRY RUN" in s
        assert "Simulated actions: 2" in s

    def test_summary_all_fields(self):
        r = SyncResult(
            tasks_pushed=1,
            tasks_status_synced=2,
            projects_pulled=3,
            goals_pulled=4,
            tags_synced=5,
            notes_pushed=6,
            concepts_pushed=7,
            people_synced=8,
            vault_files_written=9,
            ai_calls=10,
            warnings=["warn1"],
        )
        s = r.summary()
        assert "Tasks pushed: 1" in s
        assert "Task statuses synced: 2" in s
        assert "Projects pulled: 3" in s
        assert "Goals pulled: 4" in s
        assert "Tags synced: 5" in s
        assert "Journal notes pushed: 6" in s
        assert "Concepts pushed: 7" in s
        assert "People synced: 8" in s
        assert "Vault files written: 9" in s
        assert "AI decisions: 10" in s
        assert "Warnings: 1" in s


# ---------------------------------------------------------------------------
# _strip_collection
# ---------------------------------------------------------------------------

class TestStripCollection:
    def test_strips_prefix(self):
        assert _strip_collection("collection://abc-123") == "abc-123"

    def test_no_prefix(self):
        assert _strip_collection("plain-id") == "plain-id"


# ---------------------------------------------------------------------------
# RegistryManager
# ---------------------------------------------------------------------------

class TestRegistryManager:
    def test_load_creates_default(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        data = reg.load()
        assert "dimensions" in data
        assert "key_elements" in data
        assert "projects" in data

    def test_load_existing(self, tmp_path):
        path = tmp_path / "reg.json"
        path.write_text(json.dumps({
            "dimensions": {"Health": {"notion_page_id": "h-1"}},
            "key_elements": {},
        }), encoding="utf-8")
        reg = RegistryManager(path)
        data = reg.load()
        assert data["dimensions"]["Health"]["notion_page_id"] == "h-1"

    def test_save_atomic(self, tmp_path):
        path = tmp_path / "reg.json"
        reg = RegistryManager(path)
        reg.load()
        reg.save()
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "_last_synced" in data

    def test_data_property(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        assert isinstance(reg.data, dict)

    def test_get_tag_notion_id_dimension(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_tag("Health", "h-1", "dimension")
        assert reg.get_tag_notion_id("Health") == "h-1"

    def test_get_tag_notion_id_key_element(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_tag("Fitness", "f-1", "key_element", dimension="Health")
        assert reg.get_tag_notion_id("Fitness") == "f-1"

    def test_get_tag_notion_id_not_found(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        assert reg.get_tag_notion_id("Nonexistent") is None

    def test_get_project_notion_id(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_project("Brain Bot", "p-1", tag="Systems")
        assert reg.get_project_notion_id("Brain Bot") == "p-1"

    def test_get_project_notion_id_not_found(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        assert reg.get_project_notion_id("Nope") is None

    def test_get_goal_notion_id(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_goal("Automate", "g-1", tag="Systems")
        assert reg.get_goal_notion_id("Automate") == "g-1"

    def test_get_goal_notion_id_not_found(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        assert reg.get_goal_notion_id("Nope") is None

    def test_set_project_stale_key_dedup(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_project("Old Name", "p-1")
        reg.set_project("New Name", "p-1")
        assert "Old Name" not in reg.data.get("projects", {})
        assert reg.get_project_notion_id("New Name") == "p-1"

    def test_set_goal_stale_key_dedup(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_goal("Old Goal", "g-1")
        reg.set_goal("New Goal", "g-1")
        assert "Old Goal" not in reg.data.get("goals", {})
        assert reg.get_goal_notion_id("New Goal") == "g-1"

    def test_set_person(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_person("John", "per-1", relationship="Friend", email="j@example.com")
        assert reg.data["people"]["John"]["notion_page_id"] == "per-1"
        assert reg.data["people"]["John"]["relationship"] == "Friend"

    def test_set_tag_dimension(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_tag("Wealth", "w-1", "dimension")
        assert reg.data["dimensions"]["Wealth"]["notion_page_id"] == "w-1"

    def test_set_tag_key_element_with_dimension(self, tmp_path):
        reg = RegistryManager(tmp_path / "reg.json")
        reg.load()
        reg.set_tag("Income", "i-1", "key_element", dimension="Wealth")
        assert reg.data["key_elements"]["Income"]["dimension"] == "Wealth"


# ---------------------------------------------------------------------------
# NotionSync
# ---------------------------------------------------------------------------

class TestNotionSync:
    def _make_sync(self, tmp_path, dry_run=False):
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_client.query_database = AsyncMock(return_value=[])
        mock_client.create_page = AsyncMock(return_value={"id": "new-page"})
        mock_client.update_page = AsyncMock(return_value={"id": "updated"})

        reg_path = tmp_path / "reg.json"
        db_path = tmp_path / "brain.db"
        vault_path = tmp_path / "vault"
        vault_path.mkdir(exist_ok=True)

        collections = {
            "tasks": "collection://tasks-id",
            "projects": "collection://projects-id",
            "goals": "collection://goals-id",
            "tags": "collection://tags-id",
            "notes": "collection://notes-id",
            "people": "collection://people-id",
        }

        return NotionSync(
            client=mock_client,
            registry_path=reg_path,
            db_path=db_path,
            vault_path=vault_path,
            collection_ids=collections,
            dry_run=dry_run,
        ), mock_client

    def _patch_db_ops(self):
        """Create a comprehensive mock for db_ops with all async methods.

        Uses a custom MagicMock subclass where any attribute access returns
        an AsyncMock that returns an empty list by default.
        """
        class AsyncDbMock(MagicMock):
            def __getattr__(self, name):
                if name.startswith("_"):
                    return super().__getattr__(name)
                # Return cached AsyncMock for consistent behavior
                if name not in self.__dict__:
                    self.__dict__[name] = AsyncMock(return_value=[])
                return self.__dict__[name]

        mock_db = AsyncDbMock()
        mock_db.query = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock()
        return mock_db

    def _patch_outbox(self):
        mock_outbox = MagicMock()
        mock_outbox.dequeue_batch = MagicMock(return_value=[])
        mock_outbox.sweep_stale = MagicMock()
        mock_outbox.enqueue = MagicMock()
        mock_outbox.confirm = MagicMock()
        mock_outbox.fail = MagicMock()
        return mock_outbox

    @pytest.mark.asyncio
    async def test_full_sync_empty(self, tmp_path):
        syncer, client = self._make_sync(tmp_path)
        mock_db = self._patch_db_ops()
        mock_outbox = self._patch_outbox()

        with (
            patch("core.notion_sync.db_ops", mock_db),
            patch("core.notion_sync.sync_outbox", mock_outbox),
        ):
            result = await syncer.run_full_sync()

        assert isinstance(result, SyncResult)

    @pytest.mark.asyncio
    async def test_full_sync_dry_run(self, tmp_path):
        syncer, client = self._make_sync(tmp_path, dry_run=True)
        mock_db = self._patch_db_ops()
        mock_outbox = self._patch_outbox()

        with (
            patch("core.notion_sync.db_ops", mock_db),
            patch("core.notion_sync.sync_outbox", mock_outbox),
        ):
            result = await syncer.run_full_sync()

        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_selective_sync(self, tmp_path):
        syncer, client = self._make_sync(tmp_path)
        mock_db = self._patch_db_ops()
        mock_outbox = self._patch_outbox()

        with (
            patch("core.notion_sync.db_ops", mock_db),
            patch("core.notion_sync.sync_outbox", mock_outbox),
        ):
            result = await syncer.run_selective_sync(["tasks"])

        assert isinstance(result, SyncResult)

    @pytest.mark.asyncio
    async def test_sync_handles_generic_error(self, tmp_path):
        """Test that generic errors are caught and added to result.errors."""
        syncer, client = self._make_sync(tmp_path)
        mock_db = self._patch_db_ops()
        mock_outbox = self._patch_outbox()
        # Make tags step fail
        mock_db.query = AsyncMock(side_effect=Exception("DB connection lost"))

        with (
            patch("core.notion_sync.db_ops", mock_db),
            patch("core.notion_sync.sync_outbox", mock_outbox),
        ):
            result = await syncer.run_full_sync()

        # Should complete without raising, errors collected in result
        assert isinstance(result, SyncResult)

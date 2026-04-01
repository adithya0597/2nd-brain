"""Live E2E integration tests for Second Brain Telegram bot.

Tests run against the REAL database and vault for read-only verification,
and use the test_db fixture from conftest.py for any write operations.
"""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Project root for locating real vault and DB
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

REAL_DB = PROJECT_ROOT / "data" / "brain.db"
REAL_VAULT = PROJECT_ROOT / "vault"

# Custom marker for tests requiring real DB/vault
e2e = pytest.mark.skipif(
    not REAL_DB.exists(),
    reason=f"Real database not found at {REAL_DB}",
)

# Mock config before importing any bot modules (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())
import config  # noqa: E402 — conftest populates all attributes

from core.db_ops import get_cost_summary, get_icor_hierarchy, query
from core.formatter import format_cost_report, format_help
from core.notion_sync import NotionSync
from core.vault_indexer import (
    build_link_graph,
    index_to_db,
    scan_vault,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _seed_token_logs(db_path, rows):
    """Insert test rows into api_token_logs."""
    conn = sqlite3.connect(str(db_path))
    conn.executemany(
        "INSERT INTO api_token_logs (caller, model, input_tokens, output_tokens, "
        "cache_read_tokens, cache_creation_tokens, cost_estimate_usd, created_at) "
        "VALUES (?, ?, ?, ?, 0, 0, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ===========================================================================
# 1. Vault index populated (real DB)
# ===========================================================================


@e2e
class TestVaultIndexPopulated:

    @pytest.mark.asyncio
    async def test_vault_index_has_entries(self):
        """vault_index table should have entries if indexer has run."""
        rows = await query(
            "SELECT COUNT(*) AS cnt FROM vault_index", db_path=REAL_DB
        )
        assert rows[0]["cnt"] > 0, "vault_index is empty — run vault indexer first"

    @pytest.mark.asyncio
    async def test_daily_notes_indexed(self):
        """At least one Daily Note should appear in vault_index."""
        rows = await query(
            "SELECT file_path FROM vault_index WHERE file_path LIKE '%Daily Notes%' LIMIT 5",
            db_path=REAL_DB,
        )
        assert len(rows) > 0, "No Daily Notes found in vault_index"

    @pytest.mark.asyncio
    async def test_identity_files_indexed(self):
        """Identity files (ICOR, Values) should be in vault_index if they exist."""
        rows = await query(
            "SELECT file_path FROM vault_index WHERE file_path LIKE '%Identity%' LIMIT 5",
            db_path=REAL_DB,
        )
        # Identity files may or may not exist; just verify the query works
        assert isinstance(rows, list)


# ===========================================================================
# 2. Journal entries exist (real DB)
# ===========================================================================


@e2e
class TestJournalEntriesExist:

    @pytest.mark.asyncio
    async def test_journal_entries_table_has_data(self):
        """journal_entries should have at least one entry."""
        rows = await query(
            "SELECT COUNT(*) AS cnt FROM journal_entries", db_path=REAL_DB
        )
        assert rows[0]["cnt"] > 0, "journal_entries is empty"

    @pytest.mark.asyncio
    async def test_journal_entry_has_expected_fields(self):
        """Each journal entry should have date, and optional mood/energy/icor."""
        rows = await query(
            "SELECT date, mood, energy, icor_elements FROM journal_entries LIMIT 1",
            db_path=REAL_DB,
        )
        assert len(rows) == 1
        entry = rows[0]
        assert entry["date"] is not None
        # mood/energy can be NULL, just verify columns exist
        assert "mood" in entry
        assert "energy" in entry
        assert "icor_elements" in entry


# ===========================================================================
# 3. ICOR hierarchy complete (real DB)
# ===========================================================================


@e2e
class TestIcorHierarchyComplete:

    EXPECTED_DIMENSIONS = {
        "Health & Vitality",
        "Wealth & Finance",
        "Relationships",
        "Mind & Growth",
        "Purpose & Impact",
        "Systems & Environment",
    }

    @pytest.mark.asyncio
    async def test_all_six_dimensions_exist(self):
        """All 6 ICOR dimensions should exist in icor_hierarchy."""
        rows = await get_icor_hierarchy(db_path=REAL_DB)
        dimensions = {
            r["name"] for r in rows if r["level"] == "dimension"
        }
        missing = self.EXPECTED_DIMENSIONS - dimensions
        assert not missing, f"Missing dimensions: {missing}"

    @pytest.mark.asyncio
    async def test_key_elements_have_parents(self):
        """Key elements should have parent_name referencing a dimension."""
        rows = await get_icor_hierarchy(db_path=REAL_DB)
        key_elements = [r for r in rows if r["level"] == "key_element"]
        for ke in key_elements:
            assert ke["parent_name"] is not None, (
                f"Key element '{ke['name']}' has no parent"
            )


# ===========================================================================
# 4. Classification pipeline (test DB)
# ===========================================================================


class TestClassificationPipeline:

    def test_keyword_matching_health(self):
        """Keyword tier should classify health-related text correctly."""
        from core.classifier import MessageClassifier

        clf = MessageClassifier(keywords=config.DIMENSION_KEYWORDS)
        result = clf.classify("I need to schedule a workout at the gym tomorrow")
        assert not result.is_noise
        if result.matches:
            assert result.matches[0].dimension == "Health & Vitality"

    def test_keyword_matching_finance(self):
        """Finance keywords should route to Wealth & Finance."""
        from core.classifier import MessageClassifier

        clf = MessageClassifier(keywords=config.DIMENSION_KEYWORDS)
        result = clf.classify("Need to review my monthly budget and investment portfolio")
        assert not result.is_noise
        if result.matches:
            assert result.matches[0].dimension == "Wealth & Finance"

    def test_noise_filter_rejects_greetings(self):
        """Noise filter should catch casual greetings."""
        from core.classifier import MessageClassifier

        clf = MessageClassifier(keywords=config.DIMENSION_KEYWORDS)
        result = clf.classify("hey what's up")
        assert result.is_noise

    def test_actionable_detection(self):
        """Action patterns should be detected."""
        from core.classifier import MessageClassifier

        clf = MessageClassifier(keywords=config.DIMENSION_KEYWORDS)
        result = clf.classify("I need to buy groceries and schedule a dentist appointment")
        assert result.is_actionable


# ===========================================================================
# 5. Vault daily notes frontmatter (real vault)
# ===========================================================================


@e2e
class TestVaultDailyNotesFrontmatter:

    def test_daily_notes_have_frontmatter(self):
        """At least one daily note should have valid YAML frontmatter."""
        import yaml

        daily_dir = REAL_VAULT / "Daily Notes"
        if not daily_dir.exists():
            pytest.skip("Daily Notes directory not found")

        notes = sorted(daily_dir.glob("*.md"))
        assert len(notes) > 0, "No daily notes found"

        # Check the most recent note
        content = notes[-1].read_text(encoding="utf-8")
        assert content.startswith("---"), f"{notes[-1].name} has no frontmatter"

        # Extract and parse frontmatter
        parts = content.split("---", 2)
        assert len(parts) >= 3, f"{notes[-1].name} frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm is not None
        assert "type" in fm, "Frontmatter missing 'type' field"
        assert fm["type"] == "journal"
        assert "date" in fm, "Frontmatter missing 'date' field"


# ===========================================================================
# 6. Cost summary query (test DB)
# ===========================================================================


class TestCostSummaryQuery:

    @pytest.mark.asyncio
    async def test_empty_returns_empty_lists(self, test_db):
        result = await get_cost_summary(days=30, db_path=test_db)
        assert result == {"daily": [], "by_caller": [], "by_model": []}

    @pytest.mark.asyncio
    async def test_aggregation_correct(self, test_db):
        _seed_token_logs(test_db, [
            ("command_today", "claude-sonnet", 1000, 500, 0.01, "2026-03-06 10:00:00"),
            ("command_today", "claude-sonnet", 2000, 800, 0.02, "2026-03-06 11:00:00"),
            ("classifier", "claude-haiku", 500, 200, 0.003, "2026-03-06 12:00:00"),
        ])

        result = await get_cost_summary(days=30, db_path=test_db)

        # Daily: all same date => 1 row
        assert len(result["daily"]) == 1
        assert result["daily"][0]["calls"] == 3
        assert result["daily"][0]["daily_cost"] == pytest.approx(0.033, abs=1e-3)

        # By caller: 2 distinct
        assert len(result["by_caller"]) == 2
        caller_map = {r["caller"]: r for r in result["by_caller"]}
        assert caller_map["command_today"]["calls"] == 2
        assert caller_map["classifier"]["calls"] == 1

        # By model: 2 distinct
        assert len(result["by_model"]) == 2


# ===========================================================================
# 7. Cost report formatting
# ===========================================================================


class TestCostReportFormatting:

    def test_html_structure(self):
        data = {
            "daily": [
                {"date": "2026-03-06", "calls": 5, "daily_cost": 0.05,
                 "input_tokens": 5000, "output_tokens": 2000},
            ],
            "by_caller": [
                {"caller": "command_today", "calls": 3, "total_cost": 0.03,
                 "avg_input": 1000, "avg_output": 500},
            ],
            "by_model": [
                {"model": "claude-sonnet", "calls": 5, "total_cost": 0.05},
            ],
        }

        html, keyboard = format_cost_report(data, days=30)
        assert isinstance(html, str)
        assert "30" in html
        assert keyboard is None

    def test_daily_breakdown_section(self):
        data = {
            "daily": [
                {"date": "2026-03-06", "calls": 3, "daily_cost": 0.033,
                 "input_tokens": 3500, "output_tokens": 1500},
            ],
            "by_caller": [],
            "by_model": [],
        }

        html, keyboard = format_cost_report(data, days=7)
        assert "Daily Breakdown" in html
        assert "2026-03-06" in html

    def test_empty_data_shows_no_calls_message(self):
        data = {"daily": [], "by_caller": [], "by_model": []}
        html, keyboard = format_cost_report(data, days=7)
        assert "No API calls" in html


# ===========================================================================
# 8. Dry-run sync (mocked Notion client)
# ===========================================================================


class TestDryRunSync:

    @pytest.fixture()
    def mock_notion_client(self):
        client = AsyncMock()
        client.create_page = AsyncMock(return_value={"id": "page-123"})
        client.get_page = AsyncMock(return_value={"id": "page-123"})
        client.query_database = AsyncMock(return_value=[])
        return client

    @pytest.fixture()
    def registry_path(self, tmp_path):
        path = tmp_path / "notion-registry.json"
        path.write_text(json.dumps({
            "dimensions": {}, "key_elements": {},
            "goals": {}, "projects": {},
        }))
        return path

    @pytest.fixture()
    def vault_path(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        for sub in ("Identity", "Projects", "Goals", "People"):
            (vault / sub).mkdir()
        return vault

    @pytest.fixture()
    def collection_ids(self):
        return {
            "tasks": "collection://test-tasks",
            "projects": "collection://test-projects",
            "goals": "collection://test-goals",
            "tags": "collection://test-tags",
            "notes": "collection://test-notes",
            "people": "collection://test-people",
        }

    @pytest.mark.asyncio
    async def test_dry_run_produces_result_without_api_calls(
        self, mock_notion_client, registry_path, test_db, vault_path, collection_ids
    ):
        syncer = NotionSync(
            client=mock_notion_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault_path,
            collection_ids=collection_ids,
            dry_run=True,
        )

        result = await syncer.run_full_sync()

        assert result.dry_run is True
        # create_page should never be called in dry-run
        mock_notion_client.create_page.assert_not_called()


# ===========================================================================
# 9. Command handler: drift (mocked AI)
# ===========================================================================


class TestCommandHandlerDrift:

    def test_drift_command_mapping_exists(self):
        """The drift command should be registered in _COMMAND_MAP."""
        from handlers.commands import _COMMAND_MAP

        assert "drift" in _COMMAND_MAP
        brain_cmd, output_ch = _COMMAND_MAP["drift"]
        assert brain_cmd == "drift"
        assert output_ch == "brain-insights"


# ===========================================================================
# 10. Command handler: emerge (mocked AI)
# ===========================================================================


class TestCommandHandlerEmerge:

    def test_emerge_command_mapping_exists(self):
        """The emerge command should be registered in _COMMAND_MAP."""
        from handlers.commands import _COMMAND_MAP

        assert "emerge" in _COMMAND_MAP
        brain_cmd, output_ch = _COMMAND_MAP["emerge"]
        assert brain_cmd == "emerge"
        assert output_ch == "brain-insights"


# ===========================================================================
# 11. Batch file resolution (test DB + vault indexer)
# ===========================================================================


class TestBatchFileResolution:

    def test_index_and_query_vault_entries(self, test_db, temp_vault):
        """Vault indexer should scan, index, and allow title lookups."""
        # Create test vault files
        (temp_vault / "Concepts").mkdir(exist_ok=True)
        (temp_vault / "Concepts" / "Test-Concept.md").write_text(
            "---\ntype: concept\nstatus: seedling\n---\n\n# Test Concept\n\nSome content with [[Another-Concept]].\n",
            encoding="utf-8",
        )
        (temp_vault / "Concepts" / "Another-Concept.md").write_text(
            "---\ntype: concept\nstatus: growing\n---\n\n# Another Concept\n\nLinks back to [[Test-Concept]].\n",
            encoding="utf-8",
        )

        # Scan and index
        entries = scan_vault(temp_vault)
        assert len(entries) >= 2  # At least our two concept files

        incoming = build_link_graph(entries)
        index_to_db(entries, incoming, db_path=test_db)

        # Query back
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT title, type, outgoing_links_json, incoming_links_json "
            "FROM vault_index WHERE title = 'Test-Concept'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        row = dict(rows[0])
        assert row["title"] == "Test-Concept"
        outgoing = json.loads(row["outgoing_links_json"])
        assert "Another-Concept" in outgoing
        incoming_links = json.loads(row["incoming_links_json"])
        assert any("Another-Concept" in fp for fp in incoming_links)


# ===========================================================================
# 12. Tag lookup builder (NotionSync)
# ===========================================================================


class TestTagLookupBuilder:

    def test_build_tag_lookup_from_registry(self, tmp_path, test_db):
        registry_path = tmp_path / "registry.json"
        registry_data = {
            "dimensions": {
                "Health & Vitality": {"notion_page_id": "dim-1"},
                "Wealth & Finance": {"notion_page_id": "dim-2"},
            },
            "key_elements": {
                "Fitness": {"notion_page_id": "ke-1", "dimension": "Health & Vitality"},
                "Income": {"notion_page_id": "ke-2", "dimension": "Wealth & Finance"},
            },
            "goals": {},
            "projects": {},
        }
        registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

        vault = tmp_path / "vault"
        vault.mkdir()
        for sub in ("Identity", "Projects", "Goals", "People"):
            (vault / sub).mkdir()

        mock_client = AsyncMock()
        syncer = NotionSync(
            client=mock_client,
            registry_path=registry_path,
            db_path=test_db,
            vault_path=vault,
            collection_ids=config.NOTION_COLLECTIONS,
        )
        syncer._registry.load()
        lookup = syncer._build_tag_lookup()

        assert lookup["dim-1"] == "Health & Vitality"
        assert lookup["dim-2"] == "Wealth & Finance"
        assert lookup["ke-1"] == "Fitness"
        assert lookup["ke-2"] == "Income"
        assert len(lookup) == 4


# ===========================================================================
# 13. Scheduler state table (real DB)
# ===========================================================================


@e2e
class TestSchedulerStateTable:

    @pytest.mark.asyncio
    async def test_table_exists_with_expected_columns(self):
        """scheduler_state table should exist with the expected schema."""
        rows = await query(
            "PRAGMA table_info(scheduler_state)", db_path=REAL_DB
        )
        col_names = {r["name"] for r in rows}
        assert "job_name" in col_names
        assert "last_run_at" in col_names
        assert "next_run_at" in col_names
        assert "updated_at" in col_names


# ===========================================================================
# 14. Help formatter includes /brain-cost
# ===========================================================================


class TestFormatterHelpIncludesCost:

    def test_help_lists_brain_cost(self):
        """format_help() should include the /brain-cost command."""
        html, keyboard = format_help()
        assert "/brain-cost" in html

    def test_help_lists_all_core_commands(self):
        """format_help() should list key commands."""
        html, keyboard = format_help()
        for cmd in ("/brain-today", "/brain-close", "/brain-drift",
                     "/brain-status", "/brain-sync", "/brain-help"):
            assert cmd in html, f"{cmd} missing from help output"

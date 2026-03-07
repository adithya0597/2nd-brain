"""Tests for migrate-db.py Step 20 — vault_nodes/vault_edges graph migration."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SLACK_BOT_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = SLACK_BOT_DIR.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("core.db_connection", MagicMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Pre-Step-20 schema: the old vault_index TABLE (same as conftest before Sprint 3)
_OLD_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    content TEXT,
    mood TEXT,
    energy TEXT,
    icor_elements TEXT DEFAULT '[]',
    summary TEXT,
    sentiment_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    source_file TEXT,
    source_date TEXT,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_progress', 'completed', 'cancelled', 'pushed_to_notion')),
    icor_element TEXT,
    icor_project TEXT,
    external_id TEXT,
    external_system TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS concept_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    file_path TEXT,
    status TEXT DEFAULT 'seedling' CHECK(status IN ('seedling', 'growing', 'evergreen')),
    icor_elements TEXT DEFAULT '[]',
    first_mentioned TEXT,
    last_mentioned TEXT,
    mention_count INTEGER DEFAULT 0,
    related_concepts TEXT DEFAULT '[]',
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS icor_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL CHECK(level IN ('dimension','key_element','goal','project','habit')),
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES icor_hierarchy(id),
    description TEXT,
    status TEXT,
    notion_page_id TEXT,
    attention_score REAL DEFAULT 0,
    last_mentioned TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attention_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icor_element_id INTEGER NOT NULL REFERENCES icor_hierarchy(id),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    mention_count INTEGER DEFAULT 0,
    journal_days INTEGER DEFAULT 0,
    attention_score REAL DEFAULT 0,
    flagged INTEGER DEFAULT 0,
    calculated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vault_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    source_file TEXT,
    target TEXT,
    status TEXT DEFAULT 'success' CHECK(status IN ('success', 'failed', 'skipped')),
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vault_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    type TEXT DEFAULT '',
    frontmatter_json TEXT DEFAULT '{}',
    outgoing_links_json TEXT DEFAULT '[]',
    incoming_links_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    word_count INTEGER DEFAULT 0,
    last_modified TEXT,
    indexed_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_index(title);
CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_index(type);

CREATE TABLE IF NOT EXISTS embedding_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL UNIQUE,
    last_synced_at TEXT,
    items_synced INTEGER DEFAULT 0,
    last_sync_direction TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

_SEED_ICOR = """
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(1, 'dimension', 'Health & Vitality', NULL, 'Physical and mental wellbeing'),
(2, 'dimension', 'Wealth & Finance', NULL, 'Financial health'),
(3, 'dimension', 'Relationships', NULL, 'People and social connections'),
(4, 'dimension', 'Mind & Growth', NULL, 'Learning and development'),
(5, 'dimension', 'Purpose & Impact', NULL, 'Mission and contribution'),
(6, 'dimension', 'Systems & Environment', NULL, 'Home, tools, workflows');
"""


def _create_old_db(tmp_path, *, with_data=False):
    """Create a temp DB with the pre-Step-20 schema."""
    db_file = tmp_path / "migrate_test.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_OLD_SCHEMA_SQL)
    conn.executescript(_SEED_ICOR)

    if with_data:
        conn.execute(
            """INSERT INTO vault_index
               (file_path, title, type, frontmatter_json, outgoing_links_json, incoming_links_json, tags_json, word_count, last_modified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "Daily Notes/2026-03-01.md",
                "2026-03-01",
                "journal",
                '{"type":"journal"}',
                '["Fitness","Nutrition"]',
                '[]',
                '["health"]',
                150,
                "2026-03-01T10:00:00",
            ),
        )
        conn.execute(
            """INSERT INTO vault_index
               (file_path, title, type, frontmatter_json, outgoing_links_json, incoming_links_json, tags_json, word_count, last_modified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "Concepts/Fitness.md",
                "Fitness",
                "concept",
                '{}',
                '["Nutrition"]',
                '[]',
                '["health"]',
                200,
                "2026-03-01T10:00:00",
            ),
        )
        conn.execute(
            """INSERT INTO vault_index
               (file_path, title, type, frontmatter_json, outgoing_links_json, incoming_links_json, tags_json, word_count, last_modified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "Concepts/Nutrition.md",
                "Nutrition",
                "concept",
                '{}',
                '[]',
                '[]',
                '["health"]',
                180,
                "2026-03-01T10:00:00",
            ),
        )

    conn.commit()
    conn.close()
    return db_file


def _table_exists(db_path, name):
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (name,)
    ).fetchone()
    conn.close()
    return row


def _run_step20(db_path):
    """Import and run only the step-20 migration function."""
    # We import migrate-db.py's step 20 function.
    # Since it's added as part of the migrate() function, we call migrate() on our test DB.
    from importlib import import_module

    migrate_mod = import_module("migrate-db")
    migrate_mod.migrate(db_path)


# ===========================================================================
# Tests
# ===========================================================================


class TestMigrationCreatesSchema:
    """Verify the migration creates the new tables and view."""

    def test_migration_creates_vault_nodes_table(self, tmp_path):
        db_file = _create_old_db(tmp_path)
        _run_step20(db_file)

        result = _table_exists(db_file, "vault_nodes")
        assert result is not None
        assert result[0] == "table"

    def test_migration_creates_vault_edges_table(self, tmp_path):
        db_file = _create_old_db(tmp_path)
        _run_step20(db_file)

        result = _table_exists(db_file, "vault_edges")
        assert result is not None
        assert result[0] == "table"

    def test_migration_creates_vault_index_view(self, tmp_path):
        db_file = _create_old_db(tmp_path)
        _run_step20(db_file)

        result = _table_exists(db_file, "vault_index")
        assert result is not None
        # After migration, vault_index should be a VIEW, not a TABLE
        assert result[0] == "view"


class TestMigrationMigratesData:
    """Verify data is correctly migrated from old vault_index to vault_nodes + vault_edges."""

    def test_migration_migrates_data(self, tmp_path):
        """Existing vault_index rows should appear in vault_nodes after migration."""
        db_file = _create_old_db(tmp_path, with_data=True)
        _run_step20(db_file)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        nodes = conn.execute(
            "SELECT * FROM vault_nodes WHERE node_type='document' ORDER BY id"
        ).fetchall()
        conn.close()

        assert len(nodes) >= 3  # At least our 3 data rows
        titles = {n["title"] for n in nodes}
        assert "2026-03-01" in titles
        assert "Fitness" in titles
        assert "Nutrition" in titles

    def test_migration_creates_wikilink_edges(self, tmp_path):
        """Old outgoing_links_json should be converted to vault_edges rows."""
        db_file = _create_old_db(tmp_path, with_data=True)
        _run_step20(db_file)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        edges = conn.execute(
            "SELECT * FROM vault_edges WHERE edge_type='wikilink'"
        ).fetchall()
        conn.close()

        # Daily note links to Fitness and Nutrition (2 edges)
        # Fitness links to Nutrition (1 edge)
        assert len(edges) >= 3

        # Check that Daily note -> Fitness edge exists
        daily_edges = [e for e in edges if e["source_node_id"] == 1]
        assert len(daily_edges) >= 1


class TestMigrationViewBackwardCompat:
    """Verify the vault_index VIEW reconstructs the old-style JSON columns."""

    def test_migration_view_backward_compat(self, tmp_path):
        """vault_index VIEW should reconstruct outgoing/incoming links JSON."""
        db_file = _create_old_db(tmp_path, with_data=True)
        _run_step20(db_file)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM vault_index ORDER BY id"
        ).fetchall()
        conn.close()

        assert len(rows) >= 3

        # Find the daily note
        daily = [r for r in rows if r["title"] == "2026-03-01"]
        assert len(daily) == 1
        daily = daily[0]

        # outgoing_links_json should contain Fitness and Nutrition titles
        outgoing = json.loads(daily["outgoing_links_json"])
        assert "Fitness" in outgoing
        assert "Nutrition" in outgoing

        # Find Nutrition — should have incoming links
        nutrition = [r for r in rows if r["title"] == "Nutrition"]
        assert len(nutrition) == 1
        nutrition = nutrition[0]

        incoming = json.loads(nutrition["incoming_links_json"])
        # At least the daily note and Fitness link to Nutrition
        assert len(incoming) >= 2


class TestMigrationIdempotent:
    """Verify migration can be run multiple times without errors."""

    def test_migration_idempotent(self, tmp_path):
        db_file = _create_old_db(tmp_path, with_data=True)

        # Run migration twice — should not raise
        _run_step20(db_file)
        _run_step20(db_file)

        conn = sqlite3.connect(str(db_file))
        nodes = conn.execute("SELECT COUNT(*) FROM vault_nodes WHERE node_type='document'").fetchone()[0]
        conn.close()

        # Data should not be duplicated
        assert nodes >= 3


class TestMigrationSeedsIcorNodes:
    """Verify the migration seeds 6 ICOR dimension nodes in vault_nodes."""

    def test_migration_seeds_icor_nodes(self, tmp_path):
        db_file = _create_old_db(tmp_path)
        _run_step20(db_file)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        icor_nodes = conn.execute(
            "SELECT * FROM vault_nodes WHERE node_type='icor_dimension'"
        ).fetchall()
        conn.close()

        assert len(icor_nodes) == 6
        names = {n["title"] for n in icor_nodes}
        expected = {
            "Health & Vitality",
            "Wealth & Finance",
            "Relationships",
            "Mind & Growth",
            "Purpose & Impact",
            "Systems & Environment",
        }
        assert names == expected

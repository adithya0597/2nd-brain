"""Tests for performance optimizations: batch SQL, tag lookup, DB indexes."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing vault_indexer (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

from core.vault_indexer import get_linked_files
from core.notion_sync import NotionSync, RegistryManager

# ---------------------------------------------------------------------------
# Schema DDL for vault_nodes + vault_edges + vault_index VIEW
# ---------------------------------------------------------------------------

_GRAPH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vault_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    type TEXT DEFAULT '',
    frontmatter_json TEXT DEFAULT '{}',
    tags_json TEXT DEFAULT '[]',
    word_count INTEGER DEFAULT 0,
    last_modified TEXT,
    indexed_at TEXT DEFAULT (datetime('now')),
    node_type TEXT DEFAULT 'document' CHECK(node_type IN ('document','icor_dimension','icor_element','concept','tag')),
    community_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_nodes(title);
CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_nodes(type);

CREATE TABLE IF NOT EXISTS vault_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node_id INTEGER NOT NULL,
    target_node_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL CHECK(edge_type IN ('wikilink','tag_shared','semantic_similarity','icor_affinity')),
    weight REAL DEFAULT 1.0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    verified_at TEXT,
    UNIQUE(source_node_id, target_node_id, edge_type),
    FOREIGN KEY (source_node_id) REFERENCES vault_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_node_id) REFERENCES vault_nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ve_source ON vault_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_ve_target ON vault_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_ve_type ON vault_edges(edge_type);

CREATE VIEW IF NOT EXISTS vault_index AS
SELECT n.id, n.file_path, n.title, n.type, n.frontmatter_json,
    COALESCE((SELECT json_group_array(t.title) FROM vault_edges e
              JOIN vault_nodes t ON e.target_node_id=t.id
              WHERE e.source_node_id=n.id AND e.edge_type='wikilink'),'[]') AS outgoing_links_json,
    COALESCE((SELECT json_group_array(s.file_path) FROM vault_edges e
              JOIN vault_nodes s ON e.source_node_id=s.id
              WHERE e.target_node_id=n.id AND e.edge_type='wikilink'),'[]') AS incoming_links_json,
    n.tags_json, n.word_count, n.last_modified, n.indexed_at
FROM vault_nodes n WHERE n.node_type='document';
"""


# ---------------------------------------------------------------------------
# Batch file path resolution in vault_indexer
# ---------------------------------------------------------------------------

class TestBatchFilePathResolution:

    def _setup_vault_index(self, db_path: Path):
        """Populate vault_nodes + vault_edges with test data for graph traversal."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_GRAPH_SCHEMA_SQL)

        # Insert test nodes:
        # A -> B (outgoing wikilink)
        # C -> A (outgoing wikilink)
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, node_type) VALUES (?, ?, 'document')",
            ("Concepts/A.md", "A"),
        )
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, node_type) VALUES (?, ?, 'document')",
            ("Concepts/B.md", "B"),
        )
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, node_type) VALUES (?, ?, 'document')",
            ("Concepts/C.md", "C"),
        )

        # Wikilink edges: A->B (1->2), C->A (3->1)
        conn.execute(
            "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 2, 'wikilink')"
        )
        conn.execute(
            "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (3, 1, 'wikilink')"
        )
        conn.commit()
        conn.close()

    def test_get_linked_files_returns_seed_and_neighbors(self, tmp_path):
        """Batch resolution should find seed + outgoing + incoming links."""
        db_path = tmp_path / "test.db"
        self._setup_vault_index(db_path)

        results = get_linked_files(["A"], depth=1, db_path=db_path)
        titles = {r["title"] for r in results}

        # A is the seed, B is outgoing, C is incoming
        assert "A" in titles
        assert "B" in titles
        assert "C" in titles

    def test_get_linked_files_depth_0_returns_only_seeds(self, tmp_path):
        """With depth=0, only the seed nodes should be returned."""
        db_path = tmp_path / "test.db"
        self._setup_vault_index(db_path)

        results = get_linked_files(["A"], depth=0, db_path=db_path)
        titles = {r["title"] for r in results}

        assert titles == {"A"}

    def test_get_linked_files_empty_seeds(self, tmp_path):
        """Empty seed list should return empty results."""
        db_path = tmp_path / "test.db"
        self._setup_vault_index(db_path)

        results = get_linked_files([], depth=2, db_path=db_path)
        assert results == []

    def test_get_linked_files_no_duplicates(self, tmp_path):
        """Results should not contain duplicate entries."""
        db_path = tmp_path / "test.db"
        self._setup_vault_index(db_path)

        results = get_linked_files(["A"], depth=2, db_path=db_path)
        titles = [r["title"] for r in results]

        assert len(titles) == len(set(titles))

    def test_batch_resolution_uses_single_query(self, tmp_path):
        """The batch approach should issue fewer queries than N+1 per incoming link."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_GRAPH_SCHEMA_SQL)

        # Create a hub node (id=1) with many incoming wikilink edges
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, node_type) VALUES (?, ?, 'document')",
            ("Concepts/Hub.md", "Hub"),
        )
        for i in range(20):
            fp = f"Notes/Note-{i}.md"
            conn.execute(
                "INSERT INTO vault_nodes (file_path, title, node_type) VALUES (?, ?, 'document')",
                (fp, f"Note-{i}"),
            )
            # Edge from Note-{i} (id=i+2, since Hub is id=1) -> Hub (id=1)
            conn.execute(
                "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (?, 1, 'wikilink')",
                (i + 2,),
            )
        conn.commit()
        conn.close()

        # This should work correctly with batch resolution
        results = get_linked_files(["Hub"], depth=1, db_path=db_path)
        titles = {r["title"] for r in results}

        assert "Hub" in titles
        # All 20 incoming notes should be resolved
        for i in range(20):
            assert f"Note-{i}" in titles


# ---------------------------------------------------------------------------
# Tag lookup helper in notion_sync
# ---------------------------------------------------------------------------

class TestBuildTagLookup:

    def test_builds_lookup_from_dimensions_and_elements(self, tmp_path):
        """Tag lookup should map page IDs to names from both dimensions and key_elements."""
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({
            "dimensions": {
                "Health & Vitality": {"notion_page_id": "dim-1"},
                "Wealth & Finance": {"notion_page_id": "dim-2"},
            },
            "key_elements": {
                "Fitness": {"notion_page_id": "elem-1", "dimension": "Health & Vitality"},
                "Income": {"notion_page_id": "elem-2", "dimension": "Wealth & Finance"},
            },
            "goals": {},
            "projects": {},
        }))

        from unittest.mock import AsyncMock
        sync = NotionSync(
            client=AsyncMock(),
            registry_path=path,
            db_path=tmp_path / "brain.db",
            vault_path=tmp_path / "vault",
            collection_ids={"tasks": "x", "projects": "x", "goals": "x", "tags": "x", "notes": "x", "people": "x"},
        )
        sync._registry.load()
        lookup = sync._build_tag_lookup()

        assert lookup["dim-1"] == "Health & Vitality"
        assert lookup["dim-2"] == "Wealth & Finance"
        assert lookup["elem-1"] == "Fitness"
        assert lookup["elem-2"] == "Income"

    def test_empty_registry_returns_empty_lookup(self, tmp_path):
        """Empty registry should produce an empty lookup."""
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({
            "dimensions": {},
            "key_elements": {},
            "goals": {},
            "projects": {},
        }))

        from unittest.mock import AsyncMock
        sync = NotionSync(
            client=AsyncMock(),
            registry_path=path,
            db_path=tmp_path / "brain.db",
            vault_path=tmp_path / "vault",
            collection_ids={"tasks": "x", "projects": "x", "goals": "x", "tags": "x", "notes": "x", "people": "x"},
        )
        sync._registry.load()
        lookup = sync._build_tag_lookup()

        assert lookup == {}

    def test_entries_without_page_id_are_skipped(self, tmp_path):
        """Tags without notion_page_id should not appear in the lookup."""
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({
            "dimensions": {
                "Health": {"notion_page_id": "dim-1"},
                "No ID Dim": {},
            },
            "key_elements": {
                "Fitness": {"notion_page_id": "elem-1"},
                "No ID Elem": {"dimension": "Health"},
            },
            "goals": {},
            "projects": {},
        }))

        from unittest.mock import AsyncMock
        sync = NotionSync(
            client=AsyncMock(),
            registry_path=path,
            db_path=tmp_path / "brain.db",
            vault_path=tmp_path / "vault",
            collection_ids={"tasks": "x", "projects": "x", "goals": "x", "tags": "x", "notes": "x", "people": "x"},
        )
        sync._registry.load()
        lookup = sync._build_tag_lookup()

        assert len(lookup) == 2
        assert "dim-1" in lookup
        assert "elem-1" in lookup

    def test_resolve_tag_name_uses_lookup(self, tmp_path):
        """_resolve_tag_name should use _tag_lookup for O(1) lookups."""
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({
            "dimensions": {"Health": {"notion_page_id": "dim-1"}},
            "key_elements": {},
            "goals": {},
            "projects": {},
        }))

        from unittest.mock import AsyncMock
        sync = NotionSync(
            client=AsyncMock(),
            registry_path=path,
            db_path=tmp_path / "brain.db",
            vault_path=tmp_path / "vault",
            collection_ids={"tasks": "x", "projects": "x", "goals": "x", "tags": "x", "notes": "x", "people": "x"},
        )
        sync._registry.load()
        sync._tag_lookup = sync._build_tag_lookup()

        assert sync._resolve_tag_name(["dim-1"]) == "Health"
        assert sync._resolve_tag_name(["nonexistent"]) is None
        assert sync._resolve_tag_name([]) is None

    def test_resolve_tag_names_uses_lookup(self, tmp_path):
        """_resolve_tag_names should use _tag_lookup for O(1) lookups."""
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({
            "dimensions": {"Health": {"notion_page_id": "dim-1"}},
            "key_elements": {"Fitness": {"notion_page_id": "elem-1"}},
            "goals": {},
            "projects": {},
        }))

        from unittest.mock import AsyncMock
        sync = NotionSync(
            client=AsyncMock(),
            registry_path=path,
            db_path=tmp_path / "brain.db",
            vault_path=tmp_path / "vault",
            collection_ids={"tasks": "x", "projects": "x", "goals": "x", "tags": "x", "notes": "x", "people": "x"},
        )
        sync._registry.load()
        sync._tag_lookup = sync._build_tag_lookup()

        names = sync._resolve_tag_names(["dim-1", "elem-1", "nonexistent"])
        assert names == ["Health", "Fitness"]


# ---------------------------------------------------------------------------
# Migration step 13 — DB indexes
# ---------------------------------------------------------------------------

class TestMigrationIndexes:

    def _create_base_schema(self, db_path: Path):
        """Create the base tables that migrate-db.py expects to already exist."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        # Create the tables that init-db.sh would normally create
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
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
                level TEXT NOT NULL CHECK(level IN ('dimension', 'key_element', 'goal', 'project', 'habit')),
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
                status TEXT DEFAULT 'success',
                details TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        conn.close()

    def test_migration_creates_new_indexes(self, tmp_path):
        """Migration step 13 should create idx_token_logs_model and idx_token_logs_date_caller."""
        db_path = tmp_path / "brain.db"
        self._create_base_schema(db_path)

        # Add scripts dir to path for import
        scripts_dir = Path(__file__).parent.parent.parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from importlib import import_module
        migrate_mod = import_module("migrate-db")

        migrate_mod.migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='api_token_logs'"
        )
        index_names = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "idx_token_logs_model" in index_names
        assert "idx_token_logs_date_caller" in index_names

    def test_migration_is_idempotent(self, tmp_path):
        """Running migration twice should not error."""
        db_path = tmp_path / "brain.db"
        self._create_base_schema(db_path)

        scripts_dir = Path(__file__).parent.parent.parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from importlib import import_module
        migrate_mod = import_module("migrate-db")

        migrate_mod.migrate(db_path)
        migrate_mod.migrate(db_path)  # Should not raise

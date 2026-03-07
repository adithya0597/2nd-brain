"""Integration tests for graph_cache wired into vault_indexer and context_loader."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing any bot modules
_mock_config = MagicMock()
_mock_config.DB_PATH = Path("/dev/null")
_mock_config.VAULT_PATH = Path("/dev/null")
sys.modules.setdefault("config", _mock_config)

from core.graph_cache import GraphCache, cached_graph_call, get_cache, invalidate
from core.vault_indexer import (
    cached_find_files_mentioning,
    cached_get_linked_files,
    get_linked_files,
    run_full_index,
)

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure each test starts with a fresh singleton cache."""
    import core.graph_cache as mod
    mod._cache_instance = None
    yield
    mod._cache_instance = None


def _create_vault_index_db(db_path: Path):
    """Create a test DB with vault_nodes + vault_edges + vault_index VIEW."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_GRAPH_SCHEMA_SQL)

    # Build a small graph:
    #   Alpha -> Beta, Gamma (outgoing wikilinks)
    #   Beta -> Gamma (outgoing wikilink)
    #   Gamma has incoming from Alpha and Beta
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, tags_json, node_type) VALUES (?, ?, ?, 'document')",
        ("Concepts/Alpha.md", "Alpha", json.dumps(["ai"])),
    )
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, tags_json, node_type) VALUES (?, ?, ?, 'document')",
        ("Concepts/Beta.md", "Beta", json.dumps(["ml"])),
    )
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, tags_json, node_type) VALUES (?, ?, ?, 'document')",
        ("Concepts/Gamma.md", "Gamma", json.dumps(["ai", "ml"])),
    )

    # Wikilink edges: Alpha->Beta, Alpha->Gamma, Beta->Gamma
    conn.execute(
        "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 2, 'wikilink')"
    )
    conn.execute(
        "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 3, 'wikilink')"
    )
    conn.execute(
        "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (2, 3, 'wikilink')"
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCachedGetLinkedFilesReturnsSameAsUncached:
    """Verify the cached wrapper returns identical results to the raw function."""

    def test_cached_get_linked_files_returns_same_as_uncached(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_vault_index_db(db_path)

        uncached_result = get_linked_files(["Alpha"], depth=2, db_path=db_path)
        cached_result = cached_get_linked_files(seed_titles=["Alpha"], depth=2, db_path=db_path)

        # Both should return the same titles (order may vary, so compare as sets)
        uncached_titles = {r["title"] for r in uncached_result}
        cached_titles = {r["title"] for r in cached_result}
        assert uncached_titles == cached_titles
        assert len(uncached_result) == len(cached_result)


class TestSecondCallHitsCache:
    """Verify the underlying function is only invoked once for repeated calls."""

    def test_second_call_hits_cache(self):
        mock_fn = MagicMock(return_value=[{"title": "Result", "file_path": "r.md"}])

        r1 = cached_graph_call(mock_fn, "get_linked_files", seed_titles=["Alpha"], depth=2)
        r2 = cached_graph_call(mock_fn, "get_linked_files", seed_titles=["Alpha"], depth=2)

        assert r1 == r2
        mock_fn.assert_called_once()


class TestCacheInvalidatedAfterRunFullIndex:
    """Verify that run_full_index invalidates the graph cache."""

    def test_cache_invalidated_after_run_full_index(self, tmp_path):
        # Pre-populate the cache with a known entry
        cache = get_cache()
        key = GraphCache._make_key("get_linked_files", seed_titles=["Test"])
        cache.put(key, [{"title": "Stale"}])

        hit, val = cache.get(key)
        assert hit is True

        # Create a minimal vault for run_full_index to scan
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "Note.md").write_text("---\ntype: concept\n---\nHello", encoding="utf-8")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_GRAPH_SCHEMA_SQL)
        conn.close()

        run_full_index(vault_path=vault, db_path=db_path)

        # Cache should have been invalidated by run_full_index
        hit, val = cache.get(key)
        assert hit is False


class TestContextLoaderUsesCachedVariants:
    """Verify context_loader imports the cached version of vault graph functions."""

    def test_context_loader_uses_cached_variants(self, tmp_path):
        """Mock cached_find_files_mentioning in context_loader, call _gather_graph_context,
        and verify it was invoked (not the uncached version)."""
        mock_find = MagicMock(return_value=[
            {"title": "MockNote", "file_path": "Concepts/MockNote.md"},
        ])
        mock_get_linked = MagicMock(return_value=[
            {"title": "MockNote", "file_path": "Concepts/MockNote.md"},
        ])

        # Patch at the import site in context_loader (the cached versions are imported there)
        with (
            patch("core.context_loader.config.VAULT_PATH", tmp_path),
            patch(
                "core.vault_indexer.cached_find_files_mentioning",
                mock_find,
            ),
            patch(
                "core.vault_indexer.cached_get_linked_files",
                mock_get_linked,
            ),
        ):
            from core.context_loader import _gather_graph_context

            # Reload imports inside _gather_graph_context — it does a local import:
            #   from core.vault_indexer import cached_find_files_mentioning as find_files_mentioning
            # So we need to patch at the vault_indexer module level.
            result = _gather_graph_context("trace", "some topic")

        # cached_find_files_mentioning should have been called for "topic" strategy
        mock_find.assert_called_once_with("some topic")


class TestCacheKeyStabilityKwargsOrder:
    """Verify kwargs order does not affect cache key (so second call hits cache)."""

    def test_cache_key_stability_kwargs_order(self):
        call_count = 0

        def counter_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            return {"counted": call_count}

        r1 = cached_graph_call(counter_fn, "stable_fn", alpha="a", beta="b", gamma="c")
        r2 = cached_graph_call(counter_fn, "stable_fn", gamma="c", alpha="a", beta="b")

        assert r1 == r2
        assert call_count == 1, "Function should only be called once regardless of kwarg order"

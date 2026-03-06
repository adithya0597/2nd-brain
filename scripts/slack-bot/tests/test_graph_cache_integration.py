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
    """Create a test DB with vault_index table and some interconnected entries."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
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
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_index(title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_index(type)")

    # Build a small graph:
    #   Alpha -> Beta, Gamma (outgoing)
    #   Beta -> Gamma (outgoing)
    #   Gamma has incoming from Alpha and Beta
    conn.execute(
        "INSERT INTO vault_index (file_path, title, outgoing_links_json, incoming_links_json, tags_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Concepts/Alpha.md", "Alpha", json.dumps(["Beta", "Gamma"]), json.dumps([]), json.dumps(["ai"])),
    )
    conn.execute(
        "INSERT INTO vault_index (file_path, title, outgoing_links_json, incoming_links_json, tags_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Concepts/Beta.md", "Beta", json.dumps(["Gamma"]), json.dumps(["Concepts/Alpha.md"]), json.dumps(["ml"])),
    )
    conn.execute(
        "INSERT INTO vault_index (file_path, title, outgoing_links_json, incoming_links_json, tags_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "Concepts/Gamma.md",
            "Gamma",
            json.dumps([]),
            json.dumps(["Concepts/Alpha.md", "Concepts/Beta.md"]),
            json.dumps(["ai", "ml"]),
        ),
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
        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_index(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_index(type)")
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

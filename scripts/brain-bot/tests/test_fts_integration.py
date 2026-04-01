"""Integration tests for FTS5 search wired into reindex pipeline and context_loader."""

import asyncio
import json
import sqlite3
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch


SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing bot modules (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

from core.fts_index import populate_fts, search_fts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VAULT_INDEX_DDL = """
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
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
    title, content, tags, file_path UNINDEXED
);
"""


def _make_db(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with vault_index + vault_fts tables."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_VAULT_INDEX_DDL + _FTS_DDL)
    conn.close()
    return db_file


def _add_vault_entry(db_path: Path, file_path: str, title: str, tags: list[str] | None = None):
    """Insert a row into vault_index."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO vault_index (file_path, title, tags_json) VALUES (?, ?, ?)",
        (file_path, title, json.dumps(tags or [])),
    )
    conn.commit()
    conn.close()


def _write_md(vault_path: Path, rel_path: str, content: str):
    """Write a markdown file at vault_path/rel_path, creating dirs as needed."""
    full = vault_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFtsPopulatedDuringReindex:
    """Verify FTS is populated from vault_index entries and searchable."""

    def test_fts_populated_during_reindex(self, tmp_path):
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        # Create markdown files with distinct content
        _write_md(vault, "Fitness.md", textwrap.dedent("""\
            ---
            type: concept
            ---

            # Fitness

            Running and strength training improve cardiovascular health.
            Consistency is key for fitness progress.
        """))
        _write_md(vault, "Investing.md", textwrap.dedent("""\
            ---
            type: concept
            ---

            # Investing

            Index funds provide diversified market exposure.
            Dollar cost averaging reduces timing risk.
        """))

        _add_vault_entry(db_path, "Fitness.md", "Fitness", ["health"])
        _add_vault_entry(db_path, "Investing.md", "Investing", ["finance"])

        count = populate_fts(str(db_path), str(vault))
        assert count == 2

        # Search for known content
        results = search_fts("cardiovascular", db_path=str(db_path))
        assert len(results) >= 1
        assert results[0]["file_path"] == "Fitness.md"

        results = search_fts("index funds", db_path=str(db_path))
        assert len(results) >= 1
        assert results[0]["file_path"] == "Investing.md"


class TestFtsSearchRankedResultsWithSnippets:
    """Verify results are ordered by relevance and snippets contain highlight markers."""

    def test_fts_search_returns_ranked_results_with_snippets(self, tmp_path):
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        # File with MANY mentions of "automation"
        _write_md(vault, "Automation.md", textwrap.dedent("""\
            ---
            type: concept
            ---

            # Automation

            Automation simplifies repetitive tasks.
            Automation reduces human error.
            Automation scales operations efficiently.
            Automation frees time for creative work.
            Automation is key to modern workflows.
        """))
        # File with ONE mention of "automation"
        _write_md(vault, "Productivity.md", textwrap.dedent("""\
            ---
            type: concept
            ---

            # Productivity

            Being productive means focusing on high-impact tasks.
            Sometimes automation helps with repetitive work.
        """))

        _add_vault_entry(db_path, "Automation.md", "Automation", ["systems"])
        _add_vault_entry(db_path, "Productivity.md", "Productivity", ["growth"])

        populate_fts(str(db_path), str(vault))

        results = search_fts("automation", db_path=str(db_path))
        assert len(results) >= 2

        # The file with more mentions should rank first (BM25)
        assert results[0]["file_path"] == "Automation.md"

        # Snippets should contain ** highlight markers
        assert "**" in results[0]["snippet"]


class TestSpecialCharactersInQueryDontCrash:
    """Verify special FTS5 characters in queries are handled gracefully."""

    def test_special_characters_in_query_dont_crash(self, tmp_path):
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "Test.md", "---\n---\nSome content here")
        _add_vault_entry(db_path, "Test.md", "Test")
        populate_fts(str(db_path), str(vault))

        # These should not raise exceptions
        problematic_queries = [
            'hello (world)',
            'test*',
            'foo "bar"',
            '(((nested)))',
            '"unclosed quote',
            'backslash\\escape',
            '^caret',
            '{braces}',
        ]
        for query in problematic_queries:
            result = search_fts(query, db_path=str(db_path))
            assert isinstance(result, list), f"Query {query!r} should return a list"


class TestRepopulateRemovesStaleEntries:
    """Verify repopulating FTS after removing a vault_index entry removes stale results."""

    def test_repopulate_removes_stale_entries(self, tmp_path):
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "Permanent.md", "---\n---\nPermanent content about philosophy")
        _write_md(vault, "Ephemeral.md", "---\n---\nEphemeral content about xylophone uniqueness")

        _add_vault_entry(db_path, "Permanent.md", "Permanent", ["philosophy"])
        _add_vault_entry(db_path, "Ephemeral.md", "Ephemeral", ["music"])

        populate_fts(str(db_path), str(vault))

        # Both should be searchable initially
        assert len(search_fts("philosophy", db_path=str(db_path))) >= 1
        assert len(search_fts("xylophone", db_path=str(db_path))) >= 1

        # Remove the ephemeral entry from vault_index
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM vault_index WHERE file_path = 'Ephemeral.md'")
        conn.commit()
        conn.close()

        # Repopulate FTS
        populate_fts(str(db_path), str(vault))

        # Ephemeral content should no longer appear
        assert len(search_fts("xylophone", db_path=str(db_path))) == 0
        # Permanent content should still be found
        assert len(search_fts("philosophy", db_path=str(db_path))) >= 1


class TestFindContextIncludesFtsMatches:
    """Verify gather_command_context for 'find' populates fts_matches in context."""

    def test_find_context_includes_fts_matches(self, tmp_path):
        fake_fts_results = [
            {"file_path": "Notes/Test.md", "title": "Test", "snippet": "**test** content", "rank": -1.5},
        ]

        db_path = tmp_path / "test.db"
        # Create a DB with the full schema so db_ops.query works
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_VAULT_INDEX_DDL + _FTS_DDL)
        # Also create any tables needed by the _FIND_QUERIES
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY, date TEXT, content TEXT, summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_metadata (
                id INTEGER PRIMARY KEY, title TEXT, status TEXT, mention_count INTEGER, summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_items (
                id INTEGER PRIMARY KEY, description TEXT, source_date TEXT, status TEXT, icor_element TEXT
            )
        """)
        conn.commit()
        conn.close()

        with (
            patch("core.fts_index.search_fts", return_value=fake_fts_results) as mock_search,
            patch("core.context_loader.config.DB_PATH", db_path),
            patch("core.context_loader.config.VAULT_PATH", tmp_path),
            patch("core.context_loader.config.NOTION_REGISTRY_PATH", tmp_path / "nonexistent.json"),
        ):
            from core.context_loader import gather_command_context

            loop = asyncio.new_event_loop()
            try:
                context = loop.run_until_complete(
                    gather_command_context("find", user_input="test query", db_path=db_path)
                )
            finally:
                loop.close()

        assert "fts_matches" in context["db"]
        assert context["db"]["fts_matches"] == fake_fts_results


class TestFtsFallbackOnError:
    """Verify gather_command_context handles FTS errors gracefully without crashing."""

    def test_fts_fallback_on_error(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_VAULT_INDEX_DDL + _FTS_DDL)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY, date TEXT, content TEXT, summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_metadata (
                id INTEGER PRIMARY KEY, title TEXT, status TEXT, mention_count INTEGER, summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_items (
                id INTEGER PRIMARY KEY, description TEXT, source_date TEXT, status TEXT, icor_element TEXT
            )
        """)
        conn.commit()
        conn.close()

        def exploding_search(*args, **kwargs):
            raise RuntimeError("FTS5 table corrupted")

        with (
            patch("core.fts_index.search_fts", side_effect=exploding_search),
            patch("core.context_loader.config.DB_PATH", db_path),
            patch("core.context_loader.config.VAULT_PATH", tmp_path),
            patch("core.context_loader.config.NOTION_REGISTRY_PATH", tmp_path / "nonexistent.json"),
        ):
            from core.context_loader import gather_command_context

            loop = asyncio.new_event_loop()
            try:
                # Should not raise — FTS error is caught by the try/except in gather_command_context
                context = loop.run_until_complete(
                    gather_command_context("find", user_input="test query", db_path=db_path)
                )
            finally:
                loop.close()

        # fts_matches should NOT be present (error was swallowed)
        assert "fts_matches" not in context.get("db", {})
        # But other LIKE-based queries should still have run
        assert "vault_matches" in context["db"]

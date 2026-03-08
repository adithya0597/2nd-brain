"""Tests for the FTS5 full-text search module."""

import json
import sqlite3
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VAULT_INDEX_DDL = """
CREATE TABLE IF NOT EXISTS vault_index (
    file_path TEXT PRIMARY KEY,
    title TEXT,
    tags_json TEXT,
    last_modified REAL,
    content_hash TEXT
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


def _add_vault_entry(
    db_path: Path,
    file_path: str,
    title: str,
    tags: list[str] | None = None,
):
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
# Import the module under test (add slack-bot to path via conftest)
# ---------------------------------------------------------------------------

from core.fts_index import fts5_escape, populate_fts, search_fts


# ===========================================================================
# Tests
# ===========================================================================


class TestFts5Escape:
    """Unit tests for fts5_escape()."""

    def test_strips_special_characters(self):
        assert fts5_escape('hello (world) "test"') == "hello world test"

    def test_preserves_normal_words(self):
        assert fts5_escape("machine learning models") == "machine learning models"

    def test_empty_string_returns_empty(self):
        assert fts5_escape("") == ""

    def test_whitespace_only_returns_empty(self):
        assert fts5_escape("   ") == ""

    def test_special_chars_only_returns_empty(self):
        assert fts5_escape('()"*^{}\\') == ""

    def test_mixed_special_and_words(self):
        result = fts5_escape('title:"Neural Networks" AND (deep)')
        # Should keep: title, Neural, Networks, AND, deep
        assert "title" in result
        assert "Neural" in result
        assert "Networks" in result
        assert "deep" in result
        assert '"' not in result
        assert "(" not in result


class TestPopulateFts:
    """Tests for populate_fts()."""

    def test_indexes_vault_files(self, tmp_path):
        """Populate indexes the correct number of vault files."""
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        # Create 3 .md files with frontmatter
        for i, (name, body, tags) in enumerate(
            [
                ("Note-A.md", "Alpha content about science", ["science"]),
                ("Note-B.md", "Beta content about music", ["music", "art"]),
                ("Note-C.md", "Gamma content about cooking", ["food"]),
            ]
        ):
            content = textwrap.dedent(f"""\
                ---
                type: concept
                date: 2026-01-0{i + 1}
                ---

                # {name.replace('.md', '')}

                {body}
            """)
            _write_md(vault, name, content)
            _add_vault_entry(db_path, name, name.replace(".md", ""), tags)

        count = populate_fts(str(db_path), str(vault))
        assert count == 3

    def test_missing_file_indexes_with_empty_content(self, tmp_path):
        """Files listed in vault_index but missing on disk get empty content."""
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        # Add to vault_index but do NOT create file on disk
        _add_vault_entry(db_path, "Ghost-File.md", "Ghost File", ["phantom"])

        count = populate_fts(str(db_path), str(vault))
        assert count == 1

        # Should be searchable by title (via FTS on title column)
        results = search_fts("Ghost File", db_path=str(db_path))
        assert len(results) >= 1
        assert results[0]["title"] == "Ghost File"

    def test_repopulate_clears_stale_entries(self, tmp_path):
        """Repopulating after removing a vault_index entry removes stale FTS rows."""
        db_path = _make_db(tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir()

        # First populate with 2 files
        _write_md(vault, "Keep.md", "---\n---\nKeepable content here")
        _write_md(vault, "Remove.md", "---\n---\nRemovable unique xylophone")
        _add_vault_entry(db_path, "Keep.md", "Keep")
        _add_vault_entry(db_path, "Remove.md", "Remove")

        populate_fts(str(db_path), str(vault))

        # Verify both are searchable
        assert len(search_fts("xylophone", db_path=str(db_path))) == 1

        # Remove one from vault_index and repopulate
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM vault_index WHERE file_path = 'Remove.md'")
        conn.commit()
        conn.close()

        populate_fts(str(db_path), str(vault))

        # Stale entry should be gone
        assert len(search_fts("xylophone", db_path=str(db_path))) == 0
        # Kept entry still present
        assert len(search_fts("Keepable", db_path=str(db_path))) == 1


class TestSearchFts:
    """Tests for search_fts()."""

    @pytest.fixture(autouse=True)
    def _setup_indexed_vault(self, tmp_path):
        """Set up a vault with several files indexed into FTS."""
        self.db_path = _make_db(tmp_path)
        self.vault = tmp_path / "vault"
        self.vault.mkdir()

        files = [
            (
                "ML-Guide.md",
                "ML Guide",
                ["python", "ai"],
                textwrap.dedent("""\
                    ---
                    type: concept
                    ---

                    # ML Guide

                    Machine learning is a subset of artificial intelligence.
                    Deep learning uses neural networks with many layers.
                    Machine learning models require training data.
                    Machine learning evaluation uses test datasets.
                    Machine learning pipelines automate workflows.
                """),
            ),
            (
                "Neural-Networks.md",
                "Neural Networks",
                ["ai", "deep-learning"],
                textwrap.dedent("""\
                    ---
                    type: concept
                    ---

                    # Neural Networks

                    Neural networks are inspired by biological brains.
                    They consist of layers of interconnected nodes.
                """),
            ),
            (
                "Python-Basics.md",
                "Python Basics",
                ["python", "programming"],
                textwrap.dedent("""\
                    ---
                    type: concept
                    ---

                    # Python Basics

                    Python is a versatile programming language.
                    Testing in Python uses pytest and unittest.
                """),
            ),
            (
                "Testing-Strategy.md",
                "Testing Strategy",
                ["testing", "quality"],
                textwrap.dedent("""\
                    ---
                    type: concept
                    ---

                    # Testing Strategy

                    Testing is critical for software quality.
                    We use testing to verify correctness.
                    Testing ensures reliability.
                    Testing catches regressions.
                    Testing builds confidence in deployments.
                """),
            ),
        ]

        for rel_path, title, tags, content in files:
            _write_md(self.vault, rel_path, content)
            _add_vault_entry(self.db_path, rel_path, title, tags)

        populate_fts(str(self.db_path), str(self.vault))

    def test_search_by_content(self):
        """Search finds files by body content."""
        results = search_fts("machine learning", db_path=str(self.db_path))
        assert len(results) >= 1
        paths = [r["file_path"] for r in results]
        assert "ML-Guide.md" in paths

    def test_search_by_title(self):
        """Search finds files by title."""
        results = search_fts("Neural Networks", db_path=str(self.db_path))
        assert len(results) >= 1
        titles = [r["title"] for r in results]
        assert "Neural Networks" in titles

    def test_search_by_tags(self):
        """Search finds files by tags."""
        results = search_fts("python", db_path=str(self.db_path))
        assert len(results) >= 1
        # Both ML-Guide and Python-Basics have the python tag
        paths = [r["file_path"] for r in results]
        assert any("Python" in p for p in paths) or any("ML" in p for p in paths)

    def test_snippets_contain_context_markers(self):
        """Returned snippets use ** as highlight delimiters."""
        results = search_fts("machine learning", db_path=str(self.db_path))
        assert len(results) >= 1
        snippet = results[0]["snippet"]
        assert "**" in snippet

    def test_relevance_ordering(self):
        """File with more mentions of a term ranks higher."""
        results = search_fts("testing", db_path=str(self.db_path))
        assert len(results) >= 2
        # Testing-Strategy.md mentions "testing" 5 times, should rank higher
        # (bm25 returns negative scores; lower = more relevant; ORDER BY rank)
        assert results[0]["file_path"] == "Testing-Strategy.md"

    def test_empty_query_returns_empty(self):
        """Empty or whitespace query returns no results."""
        assert search_fts("", db_path=str(self.db_path)) == []
        assert search_fts("   ", db_path=str(self.db_path)) == []

    def test_special_char_only_query_returns_empty(self):
        """Query with only FTS5 special characters returns empty list."""
        assert search_fts('()"*^', db_path=str(self.db_path)) == []

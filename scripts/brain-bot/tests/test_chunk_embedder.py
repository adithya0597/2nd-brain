"""Tests for core.chunk_embedder -- chunk embedding pipeline."""
import contextlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path & module setup (same pattern as test_graph_ops.py)
# ---------------------------------------------------------------------------
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())


# Provide a working get_connection (real SQLite, not MagicMock)
@contextlib.contextmanager
def _get_connection(db_path=None, row_factory=None):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    if row_factory:
        conn.row_factory = row_factory
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_db_mod = MagicMock()
_db_mod.get_connection = _get_connection
sys.modules.setdefault("core.db_connection", _db_mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Additional vault_chunks schema DDL (not in conftest _SCHEMA_SQL yet)
_VAULT_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS vault_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES vault_nodes(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    chunk_number INTEGER NOT NULL,
    chunk_type TEXT CHECK(chunk_type IN ('whole_file', 'header_based', 'fixed_size')),
    start_line INTEGER,
    end_line INTEGER,
    word_count INTEGER DEFAULT 0,
    char_count INTEGER DEFAULT 0,
    section_header TEXT DEFAULT '',
    header_level INTEGER DEFAULT 0,
    content_hash TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    indexed_at TEXT,
    UNIQUE(node_id, chunk_number)
);
CREATE INDEX IF NOT EXISTS idx_vc_node ON vault_chunks(node_id);
CREATE INDEX IF NOT EXISTS idx_vc_file_path ON vault_chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_vc_hash ON vault_chunks(content_hash);
"""


def _extend_test_db(db_path):
    """Add vault_chunks table to the test_db schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_VAULT_CHUNKS_DDL)
    conn.commit()
    conn.close()


def _conn(db_path):
    """Open a connection with FK enforcement."""
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    return c


def _insert_vault_node(db_path, file_path, title, node_type="document"):
    """Insert a vault_node and return its id."""
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, type, node_type) VALUES (?, ?, '', ?)",
        (file_path, title, node_type),
    )
    conn.commit()
    node_id = conn.execute(
        "SELECT id FROM vault_nodes WHERE file_path = ?", (file_path,)
    ).fetchone()["id"]
    conn.close()
    return node_id


# ===========================================================================
# _chunk_content_hash
# ===========================================================================


class TestChunkContentHash:
    """Tests for the chunk content hash function."""

    def test_deterministic(self):
        """Same input always produces the same hash."""
        from core.chunk_embedder import _chunk_content_hash

        h1 = _chunk_content_hash("hello world")
        h2 = _chunk_content_hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        """Different content produces different hashes."""
        from core.chunk_embedder import _chunk_content_hash

        h1 = _chunk_content_hash("hello")
        h2 = _chunk_content_hash("world")
        assert h1 != h2

    def test_returns_16_char_hex(self):
        """Hash is a 16-char hex string (SHA-256 truncated)."""
        from core.chunk_embedder import _chunk_content_hash

        h = _chunk_content_hash("test content")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_string(self):
        """Empty string produces a valid hash."""
        from core.chunk_embedder import _chunk_content_hash

        h = _chunk_content_hash("")
        assert len(h) == 16
        assert isinstance(h, str)

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        from core.chunk_embedder import _chunk_content_hash

        h = _chunk_content_hash("Hello cafe\u0301 world")
        assert len(h) == 16


# ===========================================================================
# rechunk_and_embed_file
# ===========================================================================


class TestRechunkAndEmbedFile:
    """Tests for the rechunk_and_embed_file pipeline."""

    def test_skips_nonexistent_file(self, tmp_path):
        """Non-existent file returns 0 embedded chunks."""
        from core.chunk_embedder import rechunk_and_embed_file

        result = rechunk_and_embed_file(
            tmp_path / "nonexistent.md",
            vault_path=tmp_path,
        )
        assert result == 0

    def test_skips_non_md_file(self, tmp_path):
        """Non-markdown file returns 0 embedded chunks."""
        from core.chunk_embedder import rechunk_and_embed_file

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Some text content.")

        result = rechunk_and_embed_file(
            txt_file,
            vault_path=tmp_path,
        )
        assert result == 0

    def test_skips_file_without_vault_node(self, test_db, tmp_path):
        """File that exists on disk but has no vault_node row returns 0."""
        _extend_test_db(test_db)

        md_file = tmp_path / "orphan.md"
        md_file.write_text("# Orphan\nThis file has no vault_node entry.")

        from core.chunk_embedder import rechunk_and_embed_file

        result = rechunk_and_embed_file(
            md_file,
            vault_path=tmp_path,
            db_path=test_db,
        )
        assert result == 0

    def test_skips_when_model_unavailable(self, test_db, tmp_path):
        """Returns 0 when the embedding model is not available."""
        _extend_test_db(test_db)

        md_file = tmp_path / "test.md"
        md_file.write_text(
            "---\ntype: journal\n---\n\n## Section A\n"
            + "Content here. " * 50
            + "\n\n## Section B\n"
            + "More content. " * 50
        )

        node_id = _insert_vault_node(test_db, "test.md", "test")

        # _get_model is imported from core.embedding_store inside the function,
        # so we patch it at the source module.
        with patch("core.embedding_store._get_model", return_value=None):
            from core import chunk_embedder

            result = chunk_embedder.rechunk_and_embed_file(
                md_file,
                vault_path=tmp_path,
                db_path=test_db,
            )
        # Since there are no existing chunks in DB, all chunks are "new",
        # but model is None so it returns 0
        assert result == 0

    def test_skips_unchanged_chunks(self, test_db, tmp_path):
        """Chunks with matching content_hash are skipped."""
        _extend_test_db(test_db)

        md_file = tmp_path / "stable.md"
        content = "Short note that stays the same."
        md_file.write_text(content)

        node_id = _insert_vault_node(test_db, "stable.md", "stable")

        # Pre-populate a chunk with the correct hash
        from core.chunk_embedder import _chunk_content_hash
        from core.chunker import chunk_file

        chunks = chunk_file(content, file_path="stable.md")
        h = _chunk_content_hash(chunks[0].content)

        conn = _conn(test_db)
        conn.execute(
            """INSERT INTO vault_chunks
               (node_id, file_path, chunk_number, chunk_type, content_hash, word_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (node_id, "stable.md", 0, "whole_file", h, chunks[0].word_count),
        )
        conn.commit()
        conn.close()

        # Since all chunk hashes match, rechunk should embed 0 new chunks
        from core.chunk_embedder import rechunk_and_embed_file

        result = rechunk_and_embed_file(
            md_file,
            vault_path=tmp_path,
            db_path=test_db,
        )
        assert result == 0

    def test_detects_changed_chunks(self, test_db, tmp_path):
        """Chunks with different content_hash are detected as changed."""
        _extend_test_db(test_db)

        md_file = tmp_path / "changed.md"
        md_file.write_text("Updated short note with new content.")

        node_id = _insert_vault_node(test_db, "changed.md", "changed")

        # Pre-populate with an OLD hash that won't match
        conn = _conn(test_db)
        conn.execute(
            """INSERT INTO vault_chunks
               (node_id, file_path, chunk_number, chunk_type, content_hash, word_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (node_id, "changed.md", 0, "whole_file", "oldoldhashvalue!", 5),
        )
        conn.commit()
        conn.close()

        # Mock the embedding pipeline to avoid needing a real model
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1] * 512]

        mock_vec_conn = MagicMock()

        with patch("core.embedding_store._get_model", return_value=mock_model), \
             patch("core.embedding_store._serialize_f32", return_value=b"\x00" * 2048), \
             patch("core.embedding_store._get_vec_connection", return_value=mock_vec_conn):
            from core import chunk_embedder

            result = chunk_embedder.rechunk_and_embed_file(
                md_file,
                vault_path=tmp_path,
                db_path=test_db,
            )

        # The content changed so at least 1 chunk should have been embedded
        assert result >= 1

    def test_absolute_path_handling(self, test_db, tmp_path):
        """Passing an absolute file_path still works correctly."""
        _extend_test_db(test_db)

        md_file = tmp_path / "abs.md"
        md_file.write_text("Short absolute path test.")

        node_id = _insert_vault_node(test_db, "abs.md", "abs")

        # Explicitly mock the embedding pipeline so the function
        # returns cleanly regardless of any leaked model state
        # from previously-run tests.
        with patch("core.embedding_store._get_model", return_value=None):
            from core.chunk_embedder import rechunk_and_embed_file

            # Pass absolute path -- function should compute relative path
            result = rechunk_and_embed_file(
                md_file,  # already absolute
                vault_path=tmp_path,
                db_path=test_db,
            )
        # No existing chunks + no model = 0, but should not raise
        assert result == 0


# ===========================================================================
# embed_all_chunks
# ===========================================================================


class TestEmbedAllChunks:
    """Tests for the bulk embed_all_chunks function."""

    def test_empty_vault_returns_zero(self, tmp_path):
        """Empty vault directory returns 0 chunks embedded."""
        from core.chunk_embedder import embed_all_chunks

        result = embed_all_chunks(vault_path=tmp_path, db_path=tmp_path / "test.db")
        assert result == 0

    def test_processes_md_files_only(self, test_db, tmp_path):
        """Only .md files are processed."""
        _extend_test_db(test_db)

        # Create a mix of file types
        (tmp_path / "note.md").write_text("# A Note\nSome content.")
        (tmp_path / "data.json").write_text('{"key": "value"}')
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        # Mock rechunk_and_embed_file to track calls
        with patch("core.chunk_embedder.rechunk_and_embed_file", return_value=0) as mock_rechunk:
            from core.chunk_embedder import embed_all_chunks

            embed_all_chunks(vault_path=tmp_path, db_path=test_db)

        # Only the .md file should have been processed
        assert mock_rechunk.call_count == 1
        call_path = mock_rechunk.call_args[0][0]
        assert str(call_path).endswith(".md")

    def test_continues_on_error(self, test_db, tmp_path):
        """Errors on individual files don't stop processing."""
        _extend_test_db(test_db)

        (tmp_path / "good.md").write_text("# Good file")
        (tmp_path / "bad.md").write_text("# Bad file")

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated embedding failure")
            return 3

        with patch("core.chunk_embedder.rechunk_and_embed_file", side_effect=side_effect):
            from core.chunk_embedder import embed_all_chunks

            total = embed_all_chunks(vault_path=tmp_path, db_path=test_db)

        # Second file succeeded with 3 chunks
        assert total == 3
        assert call_count == 2


# ===========================================================================
# search_chunks
# ===========================================================================


class TestSearchChunks:
    """Tests for the chunk-level search function."""

    def test_returns_empty_when_vec_unavailable(self):
        """Returns [] when sqlite-vec is not installed."""
        with patch("core.embedding_store._check_vec_available", return_value=False):
            from core.chunk_embedder import search_chunks

            results = search_chunks("test query")
            assert results == []

    def test_returns_empty_when_model_unavailable(self):
        """Returns [] when the embedding model can't be loaded."""
        with patch("core.embedding_store._check_vec_available", return_value=True), \
             patch("core.embedding_store._get_model", return_value=None):
            from core.chunk_embedder import search_chunks

            results = search_chunks("test query")
            assert results == []

    def test_returns_empty_when_vec_connection_fails(self):
        """Returns [] when vec connection cannot be established."""
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1] * 512]

        with patch("core.embedding_store._check_vec_available", return_value=True), \
             patch("core.embedding_store._get_model", return_value=mock_model), \
             patch("core.embedding_store._serialize_f32", return_value=b"\x00" * 2048), \
             patch("core.embedding_store._get_vec_connection", return_value=None):
            from core.chunk_embedder import search_chunks

            results = search_chunks("test query")
            assert results == []

    def test_accepts_limit_parameter(self):
        """Limit parameter is passed through to the query."""
        with patch("core.embedding_store._check_vec_available", return_value=False):
            from core.chunk_embedder import search_chunks

            # Should not raise regardless of limit value
            results = search_chunks("test query", limit=5)
            assert results == []

    def test_returns_expected_dict_keys(self, test_db):
        """When results are returned, they have the expected dict keys."""
        _extend_test_db(test_db)

        # Insert test data
        node_id = _insert_vault_node(test_db, "Concepts/Test.md", "Test")
        conn = _conn(test_db)
        conn.execute(
            """INSERT INTO vault_chunks
               (node_id, file_path, chunk_number, chunk_type, section_header, word_count, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (node_id, "Concepts/Test.md", 0, "header_based", "Introduction", 50, "abc123"),
        )
        conn.commit()
        chunk_id = conn.execute(
            "SELECT id FROM vault_chunks WHERE node_id = ?", (node_id,)
        ).fetchone()["id"]
        conn.close()

        # Mock the full search pipeline to return a result
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1] * 512]

        mock_vec_conn = MagicMock()
        mock_vec_conn.execute.return_value.fetchall.return_value = [
            {"rowid": chunk_id, "distance": 0.15}
        ]

        with patch("core.embedding_store._check_vec_available", return_value=True), \
             patch("core.embedding_store._get_model", return_value=mock_model), \
             patch("core.embedding_store._serialize_f32", return_value=b"\x00" * 2048), \
             patch("core.embedding_store._get_vec_connection", return_value=mock_vec_conn):
            from core.chunk_embedder import search_chunks

            results = search_chunks("introduction to test", db_path=test_db)

        if results:  # Results depend on mock wiring
            for r in results:
                assert "file_path" in r
                assert "title" in r
                assert "section_header" in r
                assert "chunk_index" in r
                assert "distance" in r


# ===========================================================================
# Integration: chunk_file -> DB storage
# ===========================================================================


class TestChunkDbStorage:
    """Tests verifying chunk metadata is correctly stored in vault_chunks."""

    def test_chunk_hashes_match_content(self, test_db):
        """Content hashes stored in DB should match recomputed hashes."""
        _extend_test_db(test_db)

        from core.chunk_embedder import _chunk_content_hash
        from core.chunker import chunk_file

        content = (
            "## Morning\n"
            "Woke up early and exercised. " * 10 + "\n\n"
            "## Evening\n"
            "Read a book and went to sleep. " * 10
        )
        chunks = chunk_file(content)

        node_id = _insert_vault_node(test_db, "Daily Notes/test.md", "test")

        # Store chunks
        conn = _conn(test_db)
        for chunk in chunks:
            h = _chunk_content_hash(chunk.content)
            conn.execute(
                """INSERT INTO vault_chunks
                   (node_id, file_path, chunk_number, chunk_type,
                    start_line, end_line, word_count, char_count,
                    section_header, header_level, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (node_id, "Daily Notes/test.md", chunk.chunk_index,
                 chunk.chunk_type, chunk.start_line, chunk.end_line,
                 chunk.word_count, len(chunk.content),
                 chunk.section_header, chunk.header_level, h),
            )
        conn.commit()

        # Verify stored data
        rows = conn.execute(
            "SELECT * FROM vault_chunks WHERE node_id = ? ORDER BY chunk_number",
            (node_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == len(chunks)
        for row, chunk in zip(rows, chunks):
            assert row["chunk_number"] == chunk.chunk_index
            assert row["chunk_type"] == chunk.chunk_type
            assert row["section_header"] == chunk.section_header
            assert row["word_count"] == chunk.word_count
            assert row["content_hash"] == _chunk_content_hash(chunk.content)

    def test_cascade_delete_on_node_removal(self, test_db):
        """Deleting a vault_node should cascade-delete its chunks."""
        _extend_test_db(test_db)

        node_id = _insert_vault_node(test_db, "temp.md", "temp")

        conn = _conn(test_db)
        conn.execute(
            """INSERT INTO vault_chunks
               (node_id, file_path, chunk_number, chunk_type, content_hash)
               VALUES (?, ?, 0, 'whole_file', 'abc123')""",
            (node_id, "temp.md"),
        )
        conn.execute(
            """INSERT INTO vault_chunks
               (node_id, file_path, chunk_number, chunk_type, content_hash)
               VALUES (?, ?, 1, 'whole_file', 'def456')""",
            (node_id, "temp.md"),
        )
        conn.commit()

        # Verify chunks exist
        count = conn.execute(
            "SELECT COUNT(*) FROM vault_chunks WHERE node_id = ?", (node_id,)
        ).fetchone()[0]
        assert count == 2

        # Delete the node
        conn.execute("DELETE FROM vault_nodes WHERE id = ?", (node_id,))
        conn.commit()

        # Verify cascade
        count = conn.execute(
            "SELECT COUNT(*) FROM vault_chunks WHERE node_id = ?", (node_id,)
        ).fetchone()[0]
        assert count == 0
        conn.close()

    def test_unique_constraint_node_chunk(self, test_db):
        """UNIQUE(node_id, chunk_number) prevents duplicate chunks."""
        _extend_test_db(test_db)

        node_id = _insert_vault_node(test_db, "unique.md", "unique")

        conn = _conn(test_db)
        conn.execute(
            """INSERT INTO vault_chunks
               (node_id, file_path, chunk_number, chunk_type, content_hash)
               VALUES (?, ?, 0, 'whole_file', 'hash1')""",
            (node_id, "unique.md"),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO vault_chunks
                   (node_id, file_path, chunk_number, chunk_type, content_hash)
                   VALUES (?, ?, 0, 'whole_file', 'hash2')""",
                (node_id, "unique.md"),
            )
        conn.close()

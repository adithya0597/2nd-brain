"""Chunk-level embedding pipeline.

Splits vault files into semantic chunks, embeds each chunk,
and stores in vault_chunks + vec_chunks tables.
Uses content hashing to skip unchanged chunks.
"""
import hashlib
import logging
import sqlite3
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _chunk_content_hash(text: str) -> str:
    """SHA-256 hash truncated to 16 chars for chunk change detection."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def rechunk_and_embed_file(file_path: Path, vault_path: Path = None, db_path: Path = None) -> int:
    """Rechunk a single file and embed changed chunks.

    Steps:
    1. Read file from disk
    2. chunk_file() to split into chunks
    3. Compare chunk hashes with DB (skip unchanged)
    4. Batch-encode new/changed chunks
    5. Upsert vault_chunks + vec_chunks

    Returns: Number of chunks embedded (new or updated).
    """
    vault_path = vault_path or config.VAULT_PATH
    db_path = db_path or config.DB_PATH

    full_path = vault_path / file_path if not Path(file_path).is_absolute() else Path(file_path)
    if not full_path.exists() or full_path.suffix != ".md":
        return 0

    content = full_path.read_text(encoding="utf-8", errors="replace")
    rel_path = str(full_path.relative_to(vault_path))

    from core.chunker import chunk_file
    chunks = chunk_file(content, file_path=rel_path)

    # Get node_id for this file
    from core.db_connection import get_connection
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM vault_nodes WHERE file_path = ?", (rel_path,)
        ).fetchone()
        if not row:
            logger.debug("No vault_node for %s — skipping chunk embedding", rel_path)
            return 0
        node_id = row[0]

    # Get existing chunk hashes
    with get_connection(db_path) as conn:
        existing = {
            r[0]: r[1] for r in conn.execute(
                "SELECT chunk_number, content_hash FROM vault_chunks WHERE node_id = ?",
                (node_id,)
            ).fetchall()
        }

    # Determine which chunks changed
    new_chunks = []
    for chunk in chunks:
        h = _chunk_content_hash(chunk.content)
        if existing.get(chunk.chunk_index) != h:
            new_chunks.append((chunk, h))

    if not new_chunks:
        return 0

    # Embed changed chunks
    from core.embedding_store import _get_model, _serialize_f32, _truncate_vector
    model = _get_model()
    if model is None:
        return 0

    texts = [c.content for c, _ in new_chunks]
    raw_vectors = model.encode(texts, batch_size=32)
    vectors = [_truncate_vector(v) for v in raw_vectors]

    # Upsert to DB
    from core.embedding_store import _get_vec_connection
    vec_conn = _get_vec_connection(db_path)
    if vec_conn is None:
        return 0

    try:
        with get_connection(db_path) as conn:
            # Delete old chunks for this file, then reinsert all
            conn.execute("DELETE FROM vault_chunks WHERE node_id = ?", (node_id,))
            for chunk in chunks:
                h = _chunk_content_hash(chunk.content)
                conn.execute(
                    """INSERT INTO vault_chunks
                       (node_id, file_path, chunk_number, chunk_type,
                        start_line, end_line, word_count, char_count,
                        section_header, header_level, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (node_id, rel_path, chunk.chunk_index, chunk.chunk_type,
                     chunk.start_line, chunk.end_line, chunk.word_count,
                     len(chunk.content), chunk.section_header,
                     chunk.header_level, h)
                )
            conn.commit()

        # Delete old vec embeddings for this file's chunks
        # Get chunk IDs
        with get_connection(db_path) as conn:
            chunk_ids = [r[0] for r in conn.execute(
                "SELECT id FROM vault_chunks WHERE node_id = ?", (node_id,)
            ).fetchall()]

        # Delete old vectors and insert new ones
        for chunk_id in chunk_ids:
            vec_conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (chunk_id,))

        for (chunk, h), vector in zip(new_chunks, vectors):
            # Find the chunk_id for this chunk_index
            with get_connection(db_path) as conn:
                row = conn.execute(
                    "SELECT id FROM vault_chunks WHERE node_id = ? AND chunk_number = ?",
                    (node_id, chunk.chunk_index)
                ).fetchone()
                if row:
                    chunk_id = row[0]
                    vec_bytes = _serialize_f32(vector)
                    vec_conn.execute(
                        "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                        (chunk_id, vec_bytes)
                    )

        vec_conn.commit()
        return len(new_chunks)
    finally:
        vec_conn.close()


def embed_all_chunks(vault_path: Path = None, db_path: Path = None, force: bool = False) -> int:
    """Embed chunks for all vault files.

    Called during boot sequence after vault indexing.
    Returns total number of chunks embedded.
    """
    vault_path = vault_path or config.VAULT_PATH
    db_path = db_path or config.DB_PATH

    total = 0
    for md_file in sorted(vault_path.rglob("*.md")):
        try:
            count = rechunk_and_embed_file(md_file, vault_path=vault_path, db_path=db_path)
            total += count
        except Exception as e:
            logger.warning("Failed to chunk-embed %s: %s", md_file, e)

    logger.info("Chunk embedding complete: %d chunks embedded", total)
    return total


def search_chunks(query_text: str, limit: int = 10, db_path: Path = None) -> list[dict]:
    """Search chunk embeddings for similar content.

    Returns: [{file_path, title, section_header, chunk_index, distance}]
    Gracefully returns [] if unavailable.
    """
    from core.embedding_store import _get_model, _serialize_f32, _get_vec_connection, _check_vec_available

    if not _check_vec_available():
        return []

    model = _get_model()
    if model is None:
        return []

    db_path = db_path or config.DB_PATH

    from core.embedding_store import _truncate_vector
    query_vector = _truncate_vector(model.encode([query_text])[0])
    vec_bytes = _serialize_f32(query_vector)

    conn = _get_vec_connection(db_path)
    if conn is None:
        return []

    try:
        rows = conn.execute(
            "SELECT rowid, distance FROM vec_chunks "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (vec_bytes, limit)
        ).fetchall()

        results = []
        from core.db_connection import get_connection
        with get_connection(db_path, row_factory=sqlite3.Row) as db:
            for row in rows:
                chunk = db.execute(
                    """SELECT c.file_path, c.section_header, c.chunk_number,
                              n.title
                       FROM vault_chunks c
                       JOIN vault_nodes n ON c.node_id = n.id
                       WHERE c.id = ?""",
                    (row["rowid"],)
                ).fetchone()
                if chunk:
                    results.append({
                        "file_path": chunk["file_path"],
                        "title": chunk["title"],
                        "section_header": chunk["section_header"] or "",
                        "chunk_index": chunk["chunk_number"],
                        "distance": row["distance"],
                    })

        return results
    finally:
        conn.close()

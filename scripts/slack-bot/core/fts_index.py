"""FTS5 full-text search module for the Second Brain vault.

Provides populate_fts() to index vault markdown files into an FTS5 virtual
table, and search_fts() to query them with BM25-ranked results.
"""

import json
import logging
import os
import re
import sqlite3
from pathlib import Path

import config
from core.db_connection import get_connection

logger = logging.getLogger(__name__)

# Regex to strip YAML frontmatter (leading --- ... --- block)
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)

# Characters that have special meaning in FTS5 query syntax
_FTS5_SPECIAL = set('(){}"\\"*^')


def fts5_escape(text: str) -> str:
    """Strip FTS5 special characters and return space-joined words.

    This produces an implicit AND query suitable for FTS5 MATCH.
    Returns empty string for empty/whitespace-only input.
    """
    if not text or not text.strip():
        return ""
    cleaned = "".join(ch for ch in text if ch not in _FTS5_SPECIAL)
    words = cleaned.split()
    return " ".join(words)


def populate_fts(db_path: str = None, vault_path: str = None) -> int:
    """Read all vault_index rows and index their content into vault_fts.

    Args:
        db_path: Path to the SQLite database containing vault_index and vault_fts.
        vault_path: Root path of the Obsidian vault on disk.

    Returns:
        Number of entries indexed.
    """
    db_path = db_path or str(config.DB_PATH)
    vault_path = vault_path or str(config.VAULT_PATH)

    with get_connection(Path(db_path), row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT file_path, title, tags_json FROM vault_index"
        ).fetchall()

        entries = []
        for row in rows:
            file_path = row["file_path"]
            title = row["title"] or ""
            tags_json = row["tags_json"] or "[]"

            # Parse tags
            try:
                tags_list = json.loads(tags_json)
            except (json.JSONDecodeError, TypeError):
                tags_list = []
            tags_text = ", ".join(str(t) for t in tags_list) if tags_list else ""

            # Read markdown content from disk
            full_path = os.path.join(vault_path, file_path)
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    raw_content = f.read()
                # Strip YAML frontmatter
                content = _FRONTMATTER_RE.sub("", raw_content).strip()
            except (OSError, IOError):
                logger.warning("FTS index: file not found on disk: %s", full_path)
                content = ""

            entries.append((title, content, tags_text, file_path))

        # Repopulate in a transaction
        conn.execute("BEGIN")
        conn.execute("DELETE FROM vault_fts")
        conn.executemany(
            "INSERT INTO vault_fts (title, content, tags, file_path) VALUES (?, ?, ?, ?)",
            entries,
        )
        conn.execute("COMMIT")

        count = len(entries)
        logger.info("FTS index populated with %d entries", count)
        return count


def update_single_file_fts(
    file_path: Path,
    vault_path: Path = None,
    db_path: Path = None,
) -> bool:
    """Incrementally update the FTS5 index for a single file.

    Called by vault_ops post-write hooks. Avoids a full FTS rebuild
    by deleting and re-inserting only the affected row.

    Returns True if the file was indexed, False otherwise.
    """
    vault_path = vault_path or config.VAULT_PATH
    db_path = db_path or config.DB_PATH

    if not file_path.is_absolute():
        file_path = vault_path / file_path

    if not file_path.exists():
        return False

    rel_path = str(file_path.relative_to(vault_path))

    # Read file content
    try:
        raw_content = file_path.read_text(encoding="utf-8")
        content = _FRONTMATTER_RE.sub("", raw_content).strip()
    except (OSError, IOError):
        logger.warning("FTS update: could not read %s", file_path)
        return False

    # Get title and tags from vault_index (already updated by index_single_file)
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        row = conn.execute(
            "SELECT title, tags_json FROM vault_index WHERE file_path = ?",
            (rel_path,),
        ).fetchone()

        title = row["title"] if row else file_path.stem
        tags_text = ""
        if row:
            try:
                tags_list = json.loads(row["tags_json"] or "[]")
                tags_text = ", ".join(str(t) for t in tags_list)
            except (json.JSONDecodeError, TypeError):
                pass

        # Delete old FTS entry and insert new one
        conn.execute("DELETE FROM vault_fts WHERE file_path = ?", (rel_path,))
        conn.execute(
            "INSERT INTO vault_fts (title, content, tags, file_path) VALUES (?, ?, ?, ?)",
            (title, content, tags_text, rel_path),
        )
        conn.commit()

    logger.debug("FTS updated: %s", rel_path)
    return True


def search_fts(
    query_text: str, limit: int = 20, db_path: str = None
) -> list[dict]:
    """Search the FTS5 index with BM25 ranking.

    Args:
        query_text: User search query (will be escaped for FTS5 safety).
        limit: Maximum number of results to return.
        db_path: Path to SQLite database. Defaults to config.DB_PATH.

    Returns:
        List of dicts with keys: file_path, title, snippet, rank.
        Returns empty list for empty/invalid queries.
    """
    if not query_text or not query_text.strip():
        return []

    escaped = fts5_escape(query_text)
    if not escaped:
        return []

    db_path = Path(db_path) if db_path else config.DB_PATH

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        sql = (
            "SELECT file_path, title, "
            "snippet(vault_fts, 1, '**', '**', '...', 32) as snippet, "
            "bm25(vault_fts) as rank "
            "FROM vault_fts WHERE vault_fts MATCH ? "
            "ORDER BY rank LIMIT ?"
        )
        try:
            rows = conn.execute(sql, (escaped, limit)).fetchall()
        except sqlite3.OperationalError:
            # Fallback: wrap in double quotes for phrase search
            quoted = f'"{escaped}"'
            rows = conn.execute(sql, (quoted, limit)).fetchall()

        return [
            {
                "file_path": r["file_path"],
                "title": r["title"],
                "snippet": r["snippet"],
                "rank": r["rank"],
            }
            for r in rows
        ]

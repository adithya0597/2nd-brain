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


def populate_fts(db_path: str, vault_path: str) -> int:
    """Read all vault_index rows and index their content into vault_fts.

    Args:
        db_path: Path to the SQLite database containing vault_index and vault_fts.
        vault_path: Root path of the Obsidian vault on disk.

    Returns:
        Number of entries indexed.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
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
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def search_fts(
    query_text: str, limit: int = 20, db_path: str = None
) -> list[dict]:
    """Search the FTS5 index with BM25 ranking.

    Args:
        query_text: User search query (will be escaped for FTS5 safety).
        limit: Maximum number of results to return.
        db_path: Path to SQLite database. Defaults to data/brain.db relative
                 to the project root.

    Returns:
        List of dicts with keys: file_path, title, snippet, rank.
        Returns empty list for empty/invalid queries.
    """
    if not query_text or not query_text.strip():
        return []

    escaped = fts5_escape(query_text)
    if not escaped:
        return []

    if db_path is None:
        # Resolve default: scripts/slack-bot/core/ -> project root -> data/brain.db
        db_path = str(
            Path(__file__).parent.parent.parent.parent / "data" / "brain.db"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
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
    finally:
        conn.close()

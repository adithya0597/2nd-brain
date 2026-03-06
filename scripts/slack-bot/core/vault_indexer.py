"""Vault file indexer: scan markdown files, extract links/tags, build graph."""
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

import config

logger = logging.getLogger(__name__)

# Regex patterns
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z][\w/-]*)", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _extract_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _extract_wikilinks(content: str) -> list[str]:
    """Extract all [[wikilink]] targets from content."""
    return WIKILINK_RE.findall(content)


def _extract_tags(content: str) -> list[str]:
    """Extract all #tags from content (excluding frontmatter tags)."""
    # Strip frontmatter first
    body = FRONTMATTER_RE.sub("", content)
    return TAG_RE.findall(body)


def _title_from_path(path: Path) -> str:
    """Derive a title from file path (stem without extension)."""
    return path.stem


def scan_vault(vault_path: Path = None) -> list[dict]:
    """Scan all markdown files in the vault and extract metadata.

    Returns a list of dicts, one per file:
        file_path, title, type, frontmatter, outgoing_links, tags, word_count, last_modified
    """
    vault_path = vault_path or config.VAULT_PATH
    results = []

    for md_file in sorted(vault_path.rglob("*.md")):
        # Skip hidden directories and .obsidian
        rel = md_file.relative_to(vault_path)
        if any(part.startswith(".") for part in rel.parts):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Could not read %s", md_file)
            continue

        fm = _extract_frontmatter(content)
        links = _extract_wikilinks(content)
        tags = _extract_tags(content)
        word_count = len(content.split())
        mtime = datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()

        results.append({
            "file_path": str(rel),
            "title": fm.get("title") or _title_from_path(md_file),
            "type": fm.get("type", ""),
            "frontmatter": fm,
            "outgoing_links": links,
            "tags": tags,
            "word_count": word_count,
            "last_modified": mtime,
        })

    return results


def build_link_graph(entries: list[dict]) -> dict[str, list[str]]:
    """Build a reverse (incoming) link index from scan results.

    Returns {target_title: [source_file_paths]}.
    """
    incoming: dict[str, list[str]] = {}
    for entry in entries:
        for link in entry["outgoing_links"]:
            incoming.setdefault(link, []).append(entry["file_path"])
    return incoming


def index_to_db(entries: list[dict], incoming: dict[str, list[str]], db_path: Path = None):
    """Write vault index entries to SQLite.

    Creates/replaces the vault_index table with current scan results.
    """
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Ensure table exists
    cursor.execute("""
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_index(title)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_index(type)")

    # Use a transaction so interrupted reindex doesn't leave an empty table
    conn.execute("BEGIN")
    try:
        cursor.execute("DELETE FROM vault_index")

        for entry in entries:
            title = entry["title"]
            incoming_links = incoming.get(title, [])

            cursor.execute(
                "INSERT INTO vault_index "
                "(file_path, title, type, frontmatter_json, outgoing_links_json, "
                "incoming_links_json, tags_json, word_count, last_modified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry["file_path"],
                    title,
                    entry["type"],
                    json.dumps(entry["frontmatter"], default=str),
                    json.dumps(entry["outgoing_links"]),
                    json.dumps(incoming_links),
                    json.dumps(entry["tags"]),
                    entry["word_count"],
                    entry["last_modified"],
                ),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info("Indexed %d vault files to %s", len(entries), db_path)


def run_full_index(vault_path: Path = None, db_path: Path = None) -> int:
    """Scan vault and write index to DB. Returns number of files indexed."""
    entries = scan_vault(vault_path)
    incoming = build_link_graph(entries)
    index_to_db(entries, incoming, db_path)
    # Invalidate graph cache after reindexing so stale results are not served
    try:
        from core.graph_cache import invalidate as _invalidate_graph_cache
        _invalidate_graph_cache()
    except ImportError:
        pass
    return len(entries)


# ---------------------------------------------------------------------------
# Graph traversal queries (used by context_loader)
# ---------------------------------------------------------------------------


def get_linked_files(
    seed_titles: list[str],
    depth: int = 2,
    db_path: Path = None,
) -> list[dict]:
    """Walk the link graph from seed titles up to N hops.

    Returns a list of vault_index rows reachable from the seeds,
    ordered by distance (closest first).
    """
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    visited: set[str] = set()
    results: list[dict] = []
    frontier = set(seed_titles)

    for hop in range(depth + 1):
        if not frontier:
            break

        placeholders = ",".join("?" for _ in frontier)
        cursor.execute(
            f"SELECT * FROM vault_index WHERE title IN ({placeholders})",
            list(frontier),
        )
        rows = [dict(r) for r in cursor.fetchall()]

        next_frontier: set[str] = set()
        all_incoming_fps: set[str] = set()
        for row in rows:
            title = row["title"]
            if title in visited:
                continue
            visited.add(title)
            row["_hop"] = hop
            results.append(row)

            # Expand outgoing and incoming links
            outgoing = json.loads(row.get("outgoing_links_json", "[]"))
            incoming = json.loads(row.get("incoming_links_json", "[]"))
            all_incoming_fps.update(incoming)
            for link_title in outgoing:
                next_frontier.add(link_title)

        # Batch-resolve incoming file paths to titles (single query)
        if all_incoming_fps:
            fps_list = list(all_incoming_fps)
            placeholders = ",".join("?" for _ in fps_list)
            cursor.execute(
                f"SELECT file_path, title FROM vault_index WHERE file_path IN ({placeholders})",
                fps_list,
            )
            for fp_row in cursor.fetchall():
                next_frontier.add(fp_row["title"])

        frontier = next_frontier - visited

    conn.close()
    return results


def find_files_mentioning(
    topic: str,
    db_path: Path = None,
) -> list[dict]:
    """Find vault files whose content mentions a topic (via title or link)."""
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Search by title match, outgoing links containing topic, or tags
    cursor.execute(
        "SELECT * FROM vault_index WHERE "
        "title LIKE ? OR "
        "outgoing_links_json LIKE ? OR "
        "tags_json LIKE ?",
        (f"%{topic}%", f"%{topic}%", f"%{topic}%"),
    )
    results = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return results


def find_intersection_nodes(
    topic_a: str,
    topic_b: str,
    db_path: Path = None,
) -> list[dict]:
    """Find vault files that connect two topics (shared link neighbors)."""
    files_a = {r["title"] for r in find_files_mentioning(topic_a, db_path)}
    files_b = {r["title"] for r in find_files_mentioning(topic_b, db_path)}

    # Direct intersection
    shared = files_a & files_b
    if shared:
        db_path = db_path or config.DB_PATH
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in shared)
        cursor = conn.execute(
            f"SELECT * FROM vault_index WHERE title IN ({placeholders})",
            list(shared),
        )
        results = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return results

    # Try 1-hop neighbors
    linked_a = {r["title"] for r in get_linked_files(list(files_a)[:10], depth=1, db_path=db_path)}
    linked_b = {r["title"] for r in get_linked_files(list(files_b)[:10], depth=1, db_path=db_path)}
    bridge = linked_a & linked_b
    if bridge:
        db_path = db_path or config.DB_PATH
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in bridge)
        cursor = conn.execute(
            f"SELECT * FROM vault_index WHERE title IN ({placeholders})",
            list(bridge),
        )
        results = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return results

    return []


# ---------------------------------------------------------------------------
# Cache-through wrappers (use graph_cache for TTL-based caching)
# ---------------------------------------------------------------------------

from core.graph_cache import cached_graph_call, invalidate as invalidate_graph_cache


def cached_get_linked_files(seed_titles, depth=2, db_path=None):
    """Cache-through wrapper for get_linked_files."""
    return cached_graph_call(get_linked_files, "get_linked_files",
        seed_titles=seed_titles, depth=depth, db_path=db_path)


def cached_find_files_mentioning(topic, db_path=None):
    """Cache-through wrapper for find_files_mentioning."""
    return cached_graph_call(find_files_mentioning, "find_files_mentioning",
        topic=topic, db_path=db_path)


def cached_find_intersection_nodes(topic_a, topic_b, db_path=None):
    """Cache-through wrapper for find_intersection_nodes."""
    return cached_graph_call(find_intersection_nodes, "find_intersection_nodes",
        topic_a=topic_a, topic_b=topic_b, db_path=db_path)

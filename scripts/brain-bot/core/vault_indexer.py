"""Vault file indexer: scan markdown files, extract links/tags, build graph.

Uses vault_nodes + vault_edges graph schema via graph_ops module.
The vault_index VIEW provides backward compatibility for callers expecting
the old JSON-column format.
"""
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

import config
from core.db_connection import get_connection
from core.graph_ops import (
    rebuild_wikilink_edges_for_node,
    upsert_node,
)

logger = logging.getLogger(__name__)

# Regex patterns
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z][\w/-]*)", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)

# ---------------------------------------------------------------------------
# Exclusion denylist — non-knowledge files that pollute the graph
# ---------------------------------------------------------------------------
_EXCLUDED_DIRS = {"Templates", "Identity", ".obsidian"}
_EXCLUDED_FILES = {"CLAUDE.md"}


def _is_excluded(rel_path: Path) -> bool:
    """Check if a file should be excluded from the knowledge graph."""
    parts = rel_path.parts
    if parts and parts[0] in _EXCLUDED_DIRS:
        return True
    if rel_path.name in _EXCLUDED_FILES:
        return True
    return False


def _normalize_link(title: str) -> str:
    """Normalize a wikilink target for case/hyphen-insensitive matching."""
    return title.lower().replace("-", " ").replace("_", " ").strip()


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
    """Extract all tags from content: YAML frontmatter tags + body #hashtags."""
    # Body hashtags
    body = FRONTMATTER_RE.sub("", content)
    body_tags = TAG_RE.findall(body)

    # Frontmatter tags and icor_elements
    fm = _extract_frontmatter(content)
    fm_tags = []
    for key in ("tags", "icor_elements"):
        val = fm.get(key, [])
        if isinstance(val, list):
            fm_tags.extend(str(t) for t in val if t)
        elif isinstance(val, str) and val:
            fm_tags.append(val)

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in fm_tags + body_tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _title_from_path(path: Path) -> str:
    """Derive a title from file path (stem without extension)."""
    return path.stem


def _parse_single_file(md_file: Path, vault_path: Path) -> dict | None:
    """Parse a single markdown file and extract metadata.

    Returns a dict with file_path, title, type, frontmatter, outgoing_links,
    tags, word_count, last_modified -- or None if the file can't be read.
    """
    rel = md_file.relative_to(vault_path)
    if any(part.startswith(".") for part in rel.parts):
        return None
    if _is_excluded(rel):
        return None

    try:
        content = md_file.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Could not read %s", md_file)
        return None

    fm = _extract_frontmatter(content)
    links = _extract_wikilinks(content)
    tags = _extract_tags(content)
    word_count = len(content.split())
    mtime = datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()

    return {
        "file_path": str(rel),
        "title": fm.get("title") or _title_from_path(md_file),
        "type": fm.get("type", ""),
        "frontmatter": fm,
        "outgoing_links": links,
        "tags": tags,
        "word_count": word_count,
        "last_modified": mtime,
    }


def scan_vault(vault_path: Path = None) -> list[dict]:
    """Scan all markdown files in the vault and extract metadata.

    Returns a list of dicts, one per file:
        file_path, title, type, frontmatter, outgoing_links, tags, word_count, last_modified
    """
    vault_path = vault_path or config.VAULT_PATH
    results = []

    for md_file in sorted(vault_path.rglob("*.md")):
        entry = _parse_single_file(md_file, vault_path)
        if entry:
            results.append(entry)

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
    """Write vault index entries to the graph schema (vault_nodes + vault_edges).

    Replaces all document nodes and rebuilds wikilink edges from scratch.
    The incoming parameter is accepted for API compatibility but is no longer
    used -- edges encode the incoming/outgoing relationship directly.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Use a transaction so interrupted reindex doesn't leave an empty graph
        conn.execute("BEGIN")

        # Delete all existing document nodes (cascaded FK deletes their edges)
        cursor.execute("DELETE FROM vault_nodes WHERE node_type = 'document'")

        # Phase 1: Insert all nodes, collecting node_ids by file_path
        node_ids: dict[str, int] = {}
        for entry in entries:
            frontmatter_json = json.dumps(entry["frontmatter"], default=str)
            tags_json = json.dumps(entry["tags"])

            cursor.execute(
                """INSERT INTO vault_nodes
                   (file_path, title, type, frontmatter_json, tags_json,
                    word_count, last_modified, indexed_at, node_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), 'document')
                """,
                (
                    entry["file_path"],
                    entry["title"],
                    entry["type"],
                    frontmatter_json,
                    tags_json,
                    entry["word_count"],
                    entry["last_modified"],
                ),
            )
            node_ids[entry["file_path"]] = cursor.lastrowid

        # Phase 2: Build title -> node_id lookup for edge resolution
        #   Includes all node types (document + icor_dimension) so wikilinks
        #   pointing at ICOR dimension nodes also resolve correctly.
        #   Uses normalized titles for case/hyphen-insensitive matching.
        title_to_id: dict[str, int] = {}
        cursor.execute("SELECT id, title FROM vault_nodes")
        for row_id, row_title in cursor.fetchall():
            title_to_id[_normalize_link(row_title)] = row_id

        # Phase 3: Create wikilink edges for each entry
        edge_count = 0
        for entry in entries:
            source_id = node_ids.get(entry["file_path"])
            if source_id is None:
                continue

            for link_title in entry["outgoing_links"]:
                target_id = title_to_id.get(_normalize_link(link_title))
                if target_id and target_id != source_id:
                    cursor.execute(
                        """INSERT OR IGNORE INTO vault_edges
                           (source_node_id, target_node_id, edge_type, weight)
                           VALUES (?, ?, 'wikilink', 1.0)
                        """,
                        (source_id, target_id),
                    )
                    edge_count += cursor.rowcount

        conn.commit()

    logger.info(
        "Indexed %d vault files (%d wikilink edges) to %s",
        len(entries), edge_count, db_path or config.DB_PATH,
    )


def index_single_file(file_path: Path, vault_path: Path = None, db_path: Path = None):
    """Incrementally index a single vault file.

    This is the event-driven alternative to a file watcher. Called by
    vault_ops post-write hooks after any vault write operation.

    Steps:
    1. Parse the single file for metadata, links, tags
    2. Upsert its node in vault_nodes via graph_ops
    3. Rebuild outgoing wikilink edges for this node
    4. Invalidate graph cache
    """
    vault_path = vault_path or config.VAULT_PATH

    # Make sure file_path is absolute
    if not file_path.is_absolute():
        file_path = vault_path / file_path

    if not file_path.exists():
        logger.warning("index_single_file: file not found: %s", file_path)
        return

    entry = _parse_single_file(file_path, vault_path)
    if not entry:
        return

    # 1. Upsert the node
    node_id = upsert_node(
        file_path=entry["file_path"],
        title=entry["title"],
        type=entry["type"],
        frontmatter=entry["frontmatter"],
        tags=entry["tags"],
        word_count=entry["word_count"],
        last_modified=entry["last_modified"],
        node_type="document",
        db_path=db_path,
    )

    # 2. Rebuild outgoing wikilink edges (deletes old edges, creates new ones)
    rebuild_wikilink_edges_for_node(
        node_id=node_id,
        outgoing_links=entry["outgoing_links"],
        db_path=db_path,
    )

    # 3. Invalidate graph cache
    try:
        from core.graph_cache import invalidate as _invalidate_graph_cache
        _invalidate_graph_cache()
    except ImportError:
        pass

    logger.info("Incrementally indexed: %s", entry["file_path"])


def evict_deleted_nodes(vault_path: Path = None, db_path: Path = None) -> int:
    """Remove graph nodes for vault files that no longer exist on disk.

    Returns the number of nodes evicted.
    """
    from core.graph_ops import delete_node

    vault_path = vault_path or config.VAULT_PATH
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT id, file_path FROM vault_nodes WHERE node_type = 'document'"
        ).fetchall()

    deleted = 0
    for row in rows:
        full_path = vault_path / row["file_path"]
        if not full_path.exists():
            delete_node(row["file_path"], db_path=db_path)
            deleted += 1
            logger.debug("Evicted deleted node: %s", row["file_path"])

    if deleted:
        logger.info("Evicted %d nodes for deleted files", deleted)
    return deleted


def evict_excluded_nodes(db_path: Path = None) -> int:
    """Remove graph nodes matching the exclusion denylist.

    Returns the number of nodes evicted.
    """
    from core.graph_ops import delete_node

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT id, file_path FROM vault_nodes WHERE node_type = 'document'"
        ).fetchall()

    evicted = 0
    for row in rows:
        if _is_excluded(Path(row["file_path"])):
            delete_node(row["file_path"], db_path=db_path)
            evicted += 1
            logger.debug("Evicted excluded node: %s", row["file_path"])

    if evicted:
        logger.info("Evicted %d excluded nodes", evicted)
    return evicted


def index_missing_files(vault_path: Path = None, db_path: Path = None) -> int:
    """Find and index vault files not yet in the graph.

    Returns the number of newly indexed files.
    """
    vault_path = vault_path or config.VAULT_PATH

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT file_path FROM vault_nodes WHERE node_type = 'document'"
        ).fetchall()
    existing = {row["file_path"] for row in rows}

    indexed = 0
    for md_file in sorted(vault_path.rglob("*.md")):
        rel = md_file.relative_to(vault_path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if _is_excluded(rel):
            continue
        if str(rel) in existing:
            continue

        index_single_file(md_file, vault_path, db_path)
        indexed += 1

    if indexed:
        logger.info("Indexed %d missing files", indexed)
    return indexed


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
    """Walk the link graph from seed titles up to N hops via vault_edges.

    Returns a list of vault_index-compatible row dicts reachable from the
    seeds, ordered by distance (closest first). Each dict includes a ``_hop``
    field indicating the number of hops from the nearest seed.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()

        # Resolve seed titles to node IDs
        if not seed_titles:
            return []

        placeholders = ",".join("?" for _ in seed_titles)
        cursor.execute(
            f"SELECT id, title FROM vault_nodes WHERE title IN ({placeholders})",
            list(seed_titles),
        )
        seed_rows = cursor.fetchall()

        if not seed_rows:
            return []

        # Collect seed node IDs and mark them as visited
        visited_ids: set[int] = set()
        results: list[dict] = []

        # Add seed nodes themselves at hop 0
        seed_ids: list[int] = []
        for row in seed_rows:
            nid = row["id"]
            seed_ids.append(nid)
            visited_ids.add(nid)

            # Fetch the seed node's vault_index-compatible row
            cursor.execute(
                "SELECT * FROM vault_index WHERE id = ?", (nid,)
            )
            vi_row = cursor.fetchone()
            if vi_row:
                d = dict(vi_row)
                d["_hop"] = 0
                results.append(d)

        # BFS expansion using graph_ops.get_neighbors for each seed
        # We do a combined BFS across all seeds using edge queries directly
        frontier: set[int] = set(seed_ids)

        for hop in range(1, depth + 1):
            if not frontier:
                break

            next_frontier: set[int] = set()

            for nid in frontier:
                # Outgoing neighbors via wikilink edges
                for row in conn.execute(
                    "SELECT n.id FROM vault_edges e "
                    "JOIN vault_nodes n ON e.target_node_id = n.id "
                    "WHERE e.source_node_id = ? AND e.edge_type = 'wikilink'",
                    (nid,),
                ).fetchall():
                    rid = row["id"]
                    if rid not in visited_ids:
                        visited_ids.add(rid)
                        next_frontier.add(rid)

                # Incoming neighbors via wikilink edges
                for row in conn.execute(
                    "SELECT n.id FROM vault_edges e "
                    "JOIN vault_nodes n ON e.source_node_id = n.id "
                    "WHERE e.target_node_id = ? AND e.edge_type = 'wikilink'",
                    (nid,),
                ).fetchall():
                    rid = row["id"]
                    if rid not in visited_ids:
                        visited_ids.add(rid)
                        next_frontier.add(rid)

            # Batch-fetch vault_index rows for all newly discovered nodes
            if next_frontier:
                nf_list = list(next_frontier)
                ph = ",".join("?" for _ in nf_list)
                cursor.execute(
                    f"SELECT * FROM vault_index WHERE id IN ({ph})",
                    nf_list,
                )
                for vi_row in cursor.fetchall():
                    d = dict(vi_row)
                    d["_hop"] = hop
                    results.append(d)

            frontier = next_frontier

    return results


def find_files_mentioning(
    topic: str,
    db_path: Path = None,
) -> list[dict]:
    """Find vault files whose content mentions a topic (via title, links, or tags).

    Uses vault_nodes for title/tag matching and vault_edges for link-based
    discovery. Returns vault_index-compatible row dicts.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()

        # 1. Find nodes whose title matches the topic
        cursor.execute(
            "SELECT id FROM vault_nodes WHERE title LIKE ? AND node_type = 'document'",
            (f"%{topic}%",),
        )
        matching_ids: set[int] = {row["id"] for row in cursor.fetchall()}

        # 2. Find nodes whose tags match the topic
        cursor.execute(
            "SELECT id FROM vault_nodes WHERE tags_json LIKE ? AND node_type = 'document'",
            (f"%{topic}%",),
        )
        matching_ids.update(row["id"] for row in cursor.fetchall())

        # 3. Find nodes that link TO a node whose title matches the topic
        #    (i.e., they have an outgoing wikilink edge to a topic-matching node)
        cursor.execute(
            "SELECT DISTINCT e.source_node_id FROM vault_edges e "
            "JOIN vault_nodes target ON e.target_node_id = target.id "
            "WHERE e.edge_type = 'wikilink' AND target.title LIKE ?",
            (f"%{topic}%",),
        )
        matching_ids.update(row["source_node_id"] for row in cursor.fetchall())

        if not matching_ids:
            return []

        # Fetch vault_index-compatible rows for all matching nodes
        id_list = list(matching_ids)
        placeholders = ",".join("?" for _ in id_list)
        cursor.execute(
            f"SELECT * FROM vault_index WHERE id IN ({placeholders})",
            id_list,
        )
        return [dict(r) for r in cursor.fetchall()]


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
        with get_connection(db_path, row_factory=sqlite3.Row) as conn:
            placeholders = ",".join("?" for _ in shared)
            cursor = conn.execute(
                f"SELECT * FROM vault_index WHERE title IN ({placeholders})",
                list(shared),
            )
            return [dict(r) for r in cursor.fetchall()]

    # Try 1-hop neighbors
    linked_a = {r["title"] for r in get_linked_files(list(files_a)[:10], depth=1, db_path=db_path)}
    linked_b = {r["title"] for r in get_linked_files(list(files_b)[:10], depth=1, db_path=db_path)}
    bridge = linked_a & linked_b
    if bridge:
        with get_connection(db_path, row_factory=sqlite3.Row) as conn:
            placeholders = ",".join("?" for _ in bridge)
            cursor = conn.execute(
                f"SELECT * FROM vault_index WHERE title IN ({placeholders})",
                list(bridge),
            )
            return [dict(r) for r in cursor.fetchall()]

    return []


# ---------------------------------------------------------------------------
# Cache-through wrappers (use graph_cache for TTL-based caching)
# ---------------------------------------------------------------------------

from core.graph_cache import cached_graph_call


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

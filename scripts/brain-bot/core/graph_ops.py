"""Graph operations: node/edge CRUD for vault_nodes + vault_edges."""
import json
import logging
import sqlite3
from pathlib import Path

from core.db_connection import get_connection

logger = logging.getLogger(__name__)

# The six ICOR dimensions used throughout the system.
ICOR_DIMENSIONS = [
    "Health & Vitality",
    "Wealth & Finance",
    "Relationships",
    "Mind & Growth",
    "Purpose & Impact",
    "Systems & Environment",
]


def _normalize_title(title: str) -> str:
    """Normalize a title for case/hyphen-insensitive matching."""
    return title.lower().replace("-", " ").replace("_", " ").strip()


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


def upsert_node(
    file_path: str,
    title: str,
    type: str = "",
    frontmatter: dict | None = None,
    tags: list | None = None,
    word_count: int = 0,
    last_modified: str | None = None,
    node_type: str = "document",
    db_path: Path | None = None,
) -> int:
    """Insert or update a node in vault_nodes. Return the node id."""
    frontmatter_json = json.dumps(frontmatter or {}, default=str)
    tags_json = json.dumps(tags or [])

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO vault_nodes
               (file_path, title, type, frontmatter_json, tags_json,
                word_count, last_modified, indexed_at, node_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
               ON CONFLICT(file_path) DO UPDATE SET
                   title       = excluded.title,
                   type        = excluded.type,
                   frontmatter_json = excluded.frontmatter_json,
                   tags_json   = excluded.tags_json,
                   word_count  = excluded.word_count,
                   last_modified = excluded.last_modified,
                   indexed_at  = datetime('now'),
                   node_type   = excluded.node_type
            """,
            (file_path, title, type, frontmatter_json, tags_json,
             word_count, last_modified, node_type),
        )
        conn.commit()
        return cursor.lastrowid or _get_node_id(cursor, file_path)


def delete_node(file_path: str, db_path: Path | None = None) -> bool:
    """Delete a node by file_path. Cascaded edges are auto-deleted via FK.

    Returns True if a row was actually deleted.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM vault_nodes WHERE file_path = ?", (file_path,)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_node_by_path(file_path: str, db_path: Path | None = None) -> dict | None:
    """Return a node dict for the given file_path, or None."""
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.execute(
            "SELECT * FROM vault_nodes WHERE file_path = ?", (file_path,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_node_by_title(title: str, db_path: Path | None = None) -> dict | None:
    """Return a node dict for the given title, or None."""
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.execute(
            "SELECT * FROM vault_nodes WHERE title = ?", (title,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------


def upsert_edge(
    source_id: int,
    target_id: int,
    edge_type: str,
    weight: float = 1.0,
    metadata: dict | None = None,
    db_path: Path | None = None,
) -> int:
    """Insert or replace an edge. Returns the edge id."""
    metadata_json = json.dumps(metadata or {})
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO vault_edges
               (source_node_id, target_node_id, edge_type, weight, metadata_json, verified_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(source_node_id, target_node_id, edge_type) DO UPDATE SET
                   weight        = excluded.weight,
                   metadata_json = excluded.metadata_json,
                   verified_at   = datetime('now')
            """,
            (source_id, target_id, edge_type, weight, metadata_json),
        )
        conn.commit()
        return cursor.lastrowid or 0


def delete_edges_for_node(
    node_id: int,
    edge_type: str | None = None,
    direction: str = "outgoing",
    db_path: Path | None = None,
) -> int:
    """Delete edges associated with a node.

    Args:
        node_id: The node whose edges to delete.
        edge_type: If provided, only delete edges of this type.
        direction: 'outgoing' (source=node_id), 'incoming' (target=node_id),
                   or 'both'.

    Returns:
        Number of edges deleted.
    """
    clauses = []
    params: list = []

    if direction == "outgoing":
        clauses.append("source_node_id = ?")
        params.append(node_id)
    elif direction == "incoming":
        clauses.append("target_node_id = ?")
        params.append(node_id)
    elif direction == "both":
        clauses.append("(source_node_id = ? OR target_node_id = ?)")
        params.extend([node_id, node_id])
    else:
        raise ValueError(f"Invalid direction: {direction!r}")

    if edge_type is not None:
        clauses.append("edge_type = ?")
        params.append(edge_type)

    sql = f"DELETE FROM vault_edges WHERE {' AND '.join(clauses)}"

    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.rowcount


def get_outgoing_edges(
    node_id: int,
    edge_type: str | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Get outgoing edges from a node, joined with the target node info."""
    sql = (
        "SELECT e.*, n.title AS target_title, n.file_path AS target_file_path "
        "FROM vault_edges e "
        "JOIN vault_nodes n ON e.target_node_id = n.id "
        "WHERE e.source_node_id = ?"
    )
    params: list = [node_id]
    if edge_type is not None:
        sql += " AND e.edge_type = ?"
        params.append(edge_type)

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]


def get_incoming_edges(
    node_id: int,
    edge_type: str | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Get incoming edges to a node, joined with the source node info."""
    sql = (
        "SELECT e.*, n.title AS source_title, n.file_path AS source_file_path "
        "FROM vault_edges e "
        "JOIN vault_nodes n ON e.source_node_id = n.id "
        "WHERE e.target_node_id = ?"
    )
    params: list = [node_id]
    if edge_type is not None:
        sql += " AND e.edge_type = ?"
        params.append(edge_type)

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------


def get_neighbors(
    node_id: int,
    edge_types: list[str] | None = None,
    depth: int = 1,
    db_path: Path | None = None,
) -> list[dict]:
    """BFS from node_id up to *depth* hops, following edges in both directions.

    Each returned node dict includes a ``_hop`` field indicating how many
    hops from the seed.  If *edge_types* is provided, only edges of those
    types are traversed.

    Returns:
        List of node dicts with ``_hop`` annotation, ordered by distance.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        visited: set[int] = {node_id}
        results: list[dict] = []
        frontier: set[int] = {node_id}

        for hop in range(1, depth + 1):
            if not frontier:
                break

            next_frontier: set[int] = set()
            for nid in frontier:
                # Outgoing neighbours
                sql_out = (
                    "SELECT n.* FROM vault_edges e "
                    "JOIN vault_nodes n ON e.target_node_id = n.id "
                    "WHERE e.source_node_id = ?"
                )
                params_out: list = [nid]
                if edge_types:
                    placeholders = ",".join("?" for _ in edge_types)
                    sql_out += f" AND e.edge_type IN ({placeholders})"
                    params_out.extend(edge_types)

                for row in conn.execute(sql_out, params_out).fetchall():
                    rid = row["id"]
                    if rid not in visited:
                        visited.add(rid)
                        d = dict(row)
                        d["_hop"] = hop
                        results.append(d)
                        next_frontier.add(rid)

                # Incoming neighbours
                sql_in = (
                    "SELECT n.* FROM vault_edges e "
                    "JOIN vault_nodes n ON e.source_node_id = n.id "
                    "WHERE e.target_node_id = ?"
                )
                params_in: list = [nid]
                if edge_types:
                    placeholders = ",".join("?" for _ in edge_types)
                    sql_in += f" AND e.edge_type IN ({placeholders})"
                    params_in.extend(edge_types)

                for row in conn.execute(sql_in, params_in).fetchall():
                    rid = row["id"]
                    if rid not in visited:
                        visited.add(rid)
                        d = dict(row)
                        d["_hop"] = hop
                        results.append(d)
                        next_frontier.add(rid)

            frontier = next_frontier

    return results


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


def bulk_upsert_edges(
    edges: list[dict],
    db_path: Path | None = None,
) -> int:
    """Bulk upsert edges using executemany for efficiency.

    Each dict in *edges* must have keys:
        source_node_id, target_node_id, edge_type
    Optional keys: weight (default 1.0), metadata (default {}).

    Returns:
        Number of edges upserted.
    """
    if not edges:
        return 0

    rows = [
        (
            e["source_node_id"],
            e["target_node_id"],
            e["edge_type"],
            e.get("weight", 1.0),
            json.dumps(e.get("metadata", {})),
        )
        for e in edges
    ]

    with get_connection(db_path) as conn:
        conn.executemany(
            """INSERT INTO vault_edges
               (source_node_id, target_node_id, edge_type, weight, metadata_json, verified_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(source_node_id, target_node_id, edge_type) DO UPDATE SET
                   weight        = excluded.weight,
                   metadata_json = excluded.metadata_json,
                   verified_at   = datetime('now')
            """,
            rows,
        )
        conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# ICOR dimension nodes
# ---------------------------------------------------------------------------


def ensure_icor_nodes(db_path: Path | None = None) -> None:
    """Idempotently create the 6 ICOR dimension nodes.

    Uses synthetic file_path ``icor://<DimensionName>`` since these are not
    real vault files.
    """
    with get_connection(db_path) as conn:
        for dim in ICOR_DIMENSIONS:
            conn.execute(
                """INSERT OR IGNORE INTO vault_nodes
                   (file_path, title, node_type)
                   VALUES (?, ?, 'icor_dimension')
                """,
                (f"icor://{dim}", dim),
            )
        conn.commit()
    logger.info("ICOR dimension nodes ensured (%d dimensions)", len(ICOR_DIMENSIONS))


# ---------------------------------------------------------------------------
# Wikilink edge builders
# ---------------------------------------------------------------------------


def rebuild_wikilink_edges(db_path: Path | None = None) -> int:
    """Rebuild ALL wikilink edges from scratch.

    Reads every document node, parses its outgoing links (stored in
    ``vault_nodes`` or obtainable from the vault_index compatibility view),
    resolves targets by title, and creates edges.

    Deletes all existing wikilink edges first.

    Returns:
        Number of wikilink edges created.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()

        # Delete all existing wikilink edges
        cursor.execute("DELETE FROM vault_edges WHERE edge_type = 'wikilink'")

        # Build a title -> id lookup for all nodes
        cursor.execute("SELECT id, title FROM vault_nodes")
        title_to_id: dict[str, int] = {}
        for row in cursor.fetchall():
            title_to_id[row["title"]] = row["id"]

        # For document nodes, reconstruct outgoing links.
        # The vault_index view provides outgoing_links_json, but we need the
        # raw data. We can look at frontmatter or re-derive from vault files.
        # However, the migration populates vault_edges from vault_index data,
        # so post-migration we rely on per-node rebuilds (below).
        # For a full rebuild we re-read from the vault_index view if it exists,
        # or fall back to scanning vault_nodes for any stored link data.
        #
        # After migration, the canonical source for outgoing links is the
        # vault files themselves. But for efficiency, the migration step and
        # the indexer both call rebuild_wikilink_edges_for_node() per file.
        # This full rebuild is a fallback that uses the compatibility view.
        edge_count = 0
        try:
            cursor.execute(
                "SELECT id, title, outgoing_links_json "
                "FROM vault_index WHERE 1=1"
            )
            for row in cursor.fetchall():
                outgoing = json.loads(row["outgoing_links_json"] or "[]")
                source_id = title_to_id.get(row["title"])
                if source_id is None:
                    continue
                for link_title in outgoing:
                    target_id = title_to_id.get(link_title)
                    if target_id and target_id != source_id:
                        cursor.execute(
                            """INSERT OR IGNORE INTO vault_edges
                               (source_node_id, target_node_id, edge_type, weight)
                               VALUES (?, ?, 'wikilink', 1.0)
                            """,
                            (source_id, target_id),
                        )
                        edge_count += cursor.rowcount
        except sqlite3.OperationalError:
            # vault_index view might not exist yet (pre-migration)
            logger.warning("vault_index view/table not available for rebuild")

        conn.commit()

    logger.info("Rebuilt %d wikilink edges (full rebuild)", edge_count)
    return edge_count


def rebuild_wikilink_edges_for_node(
    node_id: int,
    outgoing_links: list[str],
    db_path: Path | None = None,
) -> int:
    """Rebuild wikilink edges for a single node.

    Deletes existing outgoing wikilink edges for *node_id*, then creates
    new ones based on *outgoing_links* (list of target titles).

    Returns:
        Number of wikilink edges created.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()

        # Delete existing outgoing wikilink edges for this node
        cursor.execute(
            "DELETE FROM vault_edges "
            "WHERE source_node_id = ? AND edge_type = 'wikilink'",
            (node_id,),
        )

        if not outgoing_links:
            conn.commit()
            return 0

        # Build normalized title -> id lookup for case/hyphen-insensitive matching
        cursor.execute("SELECT id, title FROM vault_nodes")
        title_to_id: dict[str, int] = {}
        for row in cursor.fetchall():
            title_to_id[_normalize_title(row["title"])] = row["id"]

        edge_count = 0
        for link_title in outgoing_links:
            target_id = title_to_id.get(_normalize_title(link_title))
            if target_id and target_id != node_id:
                cursor.execute(
                    """INSERT OR IGNORE INTO vault_edges
                       (source_node_id, target_node_id, edge_type, weight)
                       VALUES (?, ?, 'wikilink', 1.0)
                    """,
                    (node_id, target_id),
                )
                edge_count += cursor.rowcount

        conn.commit()

    logger.debug(
        "Rebuilt %d wikilink edges for node %d (%d link targets)",
        edge_count, node_id, len(outgoing_links),
    )
    return edge_count


# ---------------------------------------------------------------------------
# Tag-shared edge builders
# ---------------------------------------------------------------------------


def rebuild_tag_shared_edges(db_path: Path | None = None) -> int:
    """Rebuild ALL tag_shared edges from scratch.

    Two document nodes get a tag_shared edge if they share at least one
    tag in their tags_json array. Edge weight = number of shared tags.

    Deletes all existing tag_shared edges first.

    Returns:
        Number of tag_shared edges created.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()

        # Delete all existing tag_shared edges
        cursor.execute("DELETE FROM vault_edges WHERE edge_type = 'tag_shared'")

        # Load all document nodes with their tags
        rows = cursor.execute(
            "SELECT id, tags_json FROM vault_nodes WHERE node_type = 'document'"
        ).fetchall()

        # Build tag -> [node_id] index
        tag_to_nodes: dict[str, list[int]] = {}
        for row in rows:
            tags = json.loads(row["tags_json"] or "[]")
            for tag in tags:
                tag_lower = tag.lower().strip()
                if tag_lower:
                    tag_to_nodes.setdefault(tag_lower, []).append(row["id"])

        # Create edges between nodes sharing tags
        edge_pairs: dict[tuple[int, int], int] = {}
        for tag, node_ids in tag_to_nodes.items():
            if len(node_ids) < 2:
                continue
            for i, a in enumerate(node_ids):
                for b in node_ids[i + 1:]:
                    pair = (min(a, b), max(a, b))
                    edge_pairs[pair] = edge_pairs.get(pair, 0) + 1

        edge_count = 0
        for (src, tgt), weight in edge_pairs.items():
            cursor.execute(
                """INSERT OR IGNORE INTO vault_edges
                   (source_node_id, target_node_id, edge_type, weight)
                   VALUES (?, ?, 'tag_shared', ?)
                """,
                (src, tgt, float(weight)),
            )
            edge_count += cursor.rowcount

        conn.commit()

    logger.info("Rebuilt %d tag_shared edges", edge_count)
    return edge_count


def update_tag_shared_edges_for_file(
    file_path: str,
    db_path: Path | None = None,
) -> int:
    """Update tag_shared edges for a single file after it changes.

    Returns number of tag_shared edges created.
    """
    node = get_node_by_path(file_path, db_path=db_path)
    if node is None:
        return 0

    node_id = node["id"]
    tags = json.loads(node.get("tags_json", "[]") or "[]")
    if not tags:
        # Remove any existing tag_shared edges for this node
        delete_edges_for_node(node_id, edge_type="tag_shared", direction="both", db_path=db_path)
        return 0

    tags_lower = [t.lower().strip() for t in tags if t]
    if not tags_lower:
        delete_edges_for_node(node_id, edge_type="tag_shared", direction="both", db_path=db_path)
        return 0

    # Remove existing tag_shared edges for this node
    delete_edges_for_node(node_id, edge_type="tag_shared", direction="both", db_path=db_path)

    # Find other nodes sharing any of these tags
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT id, tags_json FROM vault_nodes "
            "WHERE node_type = 'document' AND id != ?",
            (node_id,),
        ).fetchall()

    edge_count = 0
    for row in rows:
        other_tags = json.loads(row["tags_json"] or "[]")
        other_lower = {t.lower().strip() for t in other_tags if t}
        shared = len(set(tags_lower) & other_lower)
        if shared > 0:
            upsert_edge(
                source_id=min(node_id, row["id"]),
                target_id=max(node_id, row["id"]),
                edge_type="tag_shared",
                weight=float(shared),
                db_path=db_path,
            )
            edge_count += 1

    return edge_count


# ---------------------------------------------------------------------------
# Semantic similarity edge builders
# ---------------------------------------------------------------------------


def rebuild_semantic_similarity_edges(
    top_k: int = 3,
    min_similarity: float = 0.5,
    db_path: Path | None = None,
) -> int:
    """Rebuild ALL semantic_similarity edges using vector KNN.

    For each document node with an embedding, find the top_k most similar
    documents and create semantic_similarity edges if similarity >= min_similarity.

    Deletes all existing semantic_similarity edges first.

    Returns:
        Number of semantic_similarity edges created.
    """
    try:
        from core.embedding_store import search_similar, get_file_embedding
    except ImportError:
        logger.debug("embedding_store not available — skipping semantic similarity edges")
        return 0

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        cursor = conn.cursor()

        # Delete all existing semantic_similarity edges
        cursor.execute("DELETE FROM vault_edges WHERE edge_type = 'semantic_similarity'")
        conn.commit()

        # Get all document nodes
        rows = cursor.execute(
            "SELECT id, file_path, title FROM vault_nodes WHERE node_type = 'document'"
        ).fetchall()

    if not rows:
        return 0

    # Build file_path -> node_id lookup
    path_to_id: dict[str, int] = {}
    for row in rows:
        path_to_id[row["file_path"]] = row["id"]

    edge_count = 0
    seen_pairs: set[tuple[int, int]] = set()

    for row in rows:
        # Use the file's title as the query (lightweight alternative to raw embedding KNN)
        file_emb = get_file_embedding(row["file_path"], db_path=db_path)
        if file_emb is None:
            continue

        # Search for similar files
        similar = search_similar(row["title"], limit=top_k + 1, db_path=db_path)
        source_id = row["id"]

        for match in similar:
            if match["file_path"] == row["file_path"]:
                continue  # Skip self-match

            target_id = path_to_id.get(match["file_path"])
            if target_id is None:
                continue

            # sqlite-vec returns L2 distance; convert to similarity
            # For normalized embeddings, similarity = 1 - d²/2
            distance = match["distance"]
            similarity = max(0.0, 1.0 - (distance * distance) / 2.0)
            if similarity < min_similarity:
                continue

            pair = (min(source_id, target_id), max(source_id, target_id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            upsert_edge(
                source_id=pair[0],
                target_id=pair[1],
                edge_type="semantic_similarity",
                weight=round(similarity, 4),
                db_path=db_path,
            )
            edge_count += 1

    logger.info("Rebuilt %d semantic_similarity edges", edge_count)
    return edge_count


def update_semantic_similarity_edges_for_file(
    file_path: str,
    top_k: int = 3,
    min_similarity: float = 0.5,
    db_path: Path | None = None,
) -> int:
    """Update semantic_similarity edges for a single file.

    Returns number of semantic_similarity edges created.
    """
    try:
        from core.embedding_store import search_similar, get_file_embedding
    except ImportError:
        return 0

    node = get_node_by_path(file_path, db_path=db_path)
    if node is None:
        return 0

    node_id = node["id"]

    # Check file has an embedding
    file_emb = get_file_embedding(file_path, db_path=db_path)
    if file_emb is None:
        return 0

    # Remove existing semantic_similarity edges for this node
    delete_edges_for_node(node_id, edge_type="semantic_similarity", direction="both", db_path=db_path)

    # Find similar files
    similar = search_similar(node["title"], limit=top_k + 1, db_path=db_path)

    edge_count = 0
    for match in similar:
        if match["file_path"] == file_path:
            continue

        target = get_node_by_path(match["file_path"], db_path=db_path)
        if target is None:
            continue

        distance = match["distance"]
        similarity = max(0.0, 1.0 - (distance * distance) / 2.0)
        if similarity < min_similarity:
            continue

        upsert_edge(
            source_id=min(node_id, target["id"]),
            target_id=max(node_id, target["id"]),
            edge_type="semantic_similarity",
            weight=round(similarity, 4),
            db_path=db_path,
        )
        edge_count += 1

    return edge_count


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_node_id(cursor, file_path: str) -> int:
    """Look up a node id by file_path (used when lastrowid is 0 on UPDATE)."""
    cursor.execute(
        "SELECT id FROM vault_nodes WHERE file_path = ?", (file_path,)
    )
    row = cursor.fetchone()
    return row["id"] if row else 0

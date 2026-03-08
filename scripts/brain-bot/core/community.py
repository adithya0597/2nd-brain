"""Community detection for vault knowledge graph using Louvain algorithm.

Uses networkx to partition the vault graph into communities based on
edge weights. Gracefully degrades to a no-op when networkx is not
installed.

Community IDs are stored in ``vault_nodes.community_id`` and can be
used by the context loader and search modules to scope results or
discover structural gaps.
"""
import logging
import sqlite3
from pathlib import Path

import config
from core.db_connection import get_connection

logger = logging.getLogger(__name__)

try:
    import networkx as nx

    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False
    logger.info("networkx not installed — community detection disabled")


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------


def detect_communities(
    min_weight: float = 0.1,
    edge_types: list[str] | None = None,
    db_path: Path | None = None,
) -> dict[int, int]:
    """Run Louvain community detection on the vault graph.

    Loads nodes and edges from ``vault_nodes`` / ``vault_edges``, builds a
    networkx weighted undirected graph, and runs the Louvain algorithm.

    Args:
        min_weight: Ignore edges with weight below this value.
        edge_types: If provided, only include edges of these types.
        db_path: Optional override for the database path.

    Returns:
        Mapping of ``{node_id: community_id}``. Empty dict if networkx
        is not available or the graph is empty.
    """
    if not _NX_AVAILABLE:
        return {}

    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        # Load all node IDs
        node_rows = conn.execute("SELECT id FROM vault_nodes").fetchall()
        if not node_rows:
            return {}

        # Build edge query with optional type filter
        sql = (
            "SELECT source_node_id, target_node_id, weight, edge_type "
            "FROM vault_edges WHERE weight >= ?"
        )
        params: list = [min_weight]

        if edge_types:
            placeholders = ",".join("?" for _ in edge_types)
            sql += f" AND edge_type IN ({placeholders})"
            params.extend(edge_types)

        edge_rows = conn.execute(sql, params).fetchall()

    # Build the networkx graph
    G = nx.Graph()
    for row in node_rows:
        G.add_node(row["id"])

    for row in edge_rows:
        src = row["source_node_id"]
        tgt = row["target_node_id"]
        w = row["weight"]
        # If an edge already exists (e.g. from multiple edge types),
        # accumulate the weight.
        if G.has_edge(src, tgt):
            G[src][tgt]["weight"] += w
        else:
            G.add_edge(src, tgt, weight=w)

    # Remove isolated nodes (no edges) — Louvain handles them, but they
    # clutter the results with singleton communities.
    isolates = list(nx.isolates(G))
    G.remove_nodes_from(isolates)

    if G.number_of_nodes() == 0:
        return {}

    # Run Louvain
    try:
        communities = nx.community.louvain_communities(G, weight="weight")
    except Exception:
        logger.debug("Louvain community detection failed", exc_info=True)
        return {}

    # Convert the list-of-sets result to {node_id: community_id}
    mapping: dict[int, int] = {}
    for community_id, members in enumerate(communities):
        for node_id in members:
            mapping[node_id] = community_id

    logger.info(
        "Detected %d communities across %d nodes (%d isolates excluded)",
        len(communities),
        len(mapping),
        len(isolates),
    )
    return mapping


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def update_community_ids(db_path: Path | None = None) -> int:
    """Run community detection and persist results to ``vault_nodes``.

    Updates ``vault_nodes.community_id`` for each node in the mapping.
    Nodes not in the mapping (e.g. isolates) are set to ``NULL``.

    Returns:
        Number of nodes whose community_id was updated.
    """
    mapping = detect_communities(db_path=db_path)
    if not mapping:
        return 0

    with get_connection(db_path) as conn:
        # Reset all community IDs first
        conn.execute("UPDATE vault_nodes SET community_id = NULL")

        count = 0
        for node_id, community_id in mapping.items():
            cursor = conn.execute(
                "UPDATE vault_nodes SET community_id = ? WHERE id = ?",
                (community_id, node_id),
            )
            count += cursor.rowcount

        conn.commit()

    logger.info("Updated community_id for %d nodes", count)
    return count


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_community_members(
    community_id: int,
    db_path: Path | None = None,
) -> list[dict]:
    """Get all document nodes in a specific community.

    Args:
        community_id: The community ID to query.
        db_path: Optional override for the database path.

    Returns:
        List of node dicts (document nodes only).
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT * FROM vault_nodes "
            "WHERE community_id = ? AND node_type = 'document'",
            (community_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_structural_gaps(db_path: Path | None = None) -> list[dict]:
    """Find communities that have no ICOR affinity edges.

    A "structural gap" is a cluster of related documents that are not
    connected to any ICOR dimension. This can reveal content that the
    ICOR framework does not yet cover, or files that need reclassification.

    Returns:
        List of dicts: ``{community_id, member_count, sample_titles}``.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        # Get all distinct community IDs (non-NULL) with member counts
        community_rows = conn.execute(
            "SELECT community_id, COUNT(*) AS member_count "
            "FROM vault_nodes "
            "WHERE community_id IS NOT NULL AND node_type = 'document' "
            "GROUP BY community_id"
        ).fetchall()

        if not community_rows:
            return []

        gaps: list[dict] = []
        for crow in community_rows:
            cid = crow["community_id"]
            member_count = crow["member_count"]

            # Check if ANY node in this community has an icor_affinity edge
            has_icor = conn.execute(
                "SELECT 1 FROM vault_edges e "
                "JOIN vault_nodes n ON e.source_node_id = n.id "
                "WHERE n.community_id = ? AND e.edge_type = 'icor_affinity' "
                "LIMIT 1",
                (cid,),
            ).fetchone()

            if has_icor:
                continue

            # This community has no ICOR connections — it's a gap
            sample_rows = conn.execute(
                "SELECT title FROM vault_nodes "
                "WHERE community_id = ? AND node_type = 'document' "
                "ORDER BY last_modified DESC LIMIT 5",
                (cid,),
            ).fetchall()
            sample_titles = [r["title"] for r in sample_rows]

            gaps.append({
                "community_id": cid,
                "member_count": member_count,
                "sample_titles": sample_titles,
            })

    return gaps


def get_bridge_nodes(
    min_communities: int = 2,
    db_path: Path | None = None,
) -> list[dict]:
    """Find nodes that bridge multiple communities.

    A "bridge node" has edges to nodes in at least ``min_communities``
    distinct communities. These are high-value connector documents in
    the knowledge graph.

    Args:
        min_communities: Minimum number of distinct communities a node
            must connect to.
        db_path: Optional override for the database path.

    Returns:
        List of node dicts with an additional ``community_count`` field,
        sorted by community_count descending.
    """
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        # For each document node, count distinct communities of its neighbors
        rows = conn.execute(
            """
            SELECT n.*, COUNT(DISTINCT n2.community_id) AS community_count
            FROM vault_nodes n
            JOIN vault_edges e ON (
                e.source_node_id = n.id OR e.target_node_id = n.id
            )
            JOIN vault_nodes n2 ON (
                n2.id = CASE
                    WHEN e.source_node_id = n.id THEN e.target_node_id
                    ELSE e.source_node_id
                END
            )
            WHERE n.node_type = 'document'
              AND n2.community_id IS NOT NULL
              AND n2.community_id != COALESCE(n.community_id, -1)
            GROUP BY n.id
            HAVING COUNT(DISTINCT n2.community_id) >= ?
            ORDER BY community_count DESC
            """,
            (min_communities,),
        ).fetchall()

        return [dict(row) for row in rows]

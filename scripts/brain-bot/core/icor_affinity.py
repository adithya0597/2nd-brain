"""ICOR affinity: connect vault files to ICOR dimensions via cosine similarity.

Each vault file gets scored against the six ICOR dimension reference
embeddings (stored in ``vec_icor``). Scores above the threshold produce
``icor_affinity`` edges in ``vault_edges``, linking the document node to
the corresponding ICOR dimension node.

This module is called:
- Incrementally from ``vault_ops._on_vault_write()`` after each vault write
- In bulk from ``rebuild_all_icor_edges()`` at boot or reindex time

Dependencies:
- ``core.embedding_store`` for vec_vault / vec_icor access
- ``core.graph_ops`` for node/edge CRUD
- ``core.db_connection`` for standard DB access
"""
import logging
import math
import sqlite3
import struct
from pathlib import Path

import config
from core.db_connection import get_connection

logger = logging.getLogger(__name__)

# Files with max cosine similarity below this threshold against ALL
# reference embeddings for a dimension are NOT linked to that dimension.
ICOR_AFFINITY_THRESHOLD = 0.52
ICOR_AFFINITY_TOP_K = 2  # Keep at most top-K dimensions per file

# Prefixes for files that should be skipped (non-knowledge content)
_AFFINITY_SKIP_PREFIXES = ("Templates/", "Identity/", "CLAUDE")


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def _cosine_similarity(vec_a_bytes: bytes, vec_b_bytes: bytes, dim: int | None = None) -> float:
    """Compute cosine similarity between two serialized float vectors.

    Both inputs are raw bytes produced by ``struct.pack(f"{dim}f", *vec)``
    where *dim* matches ``config.EMBEDDING_DIM``.
    Returns a float in [-1, 1], or 0.0 if either vector has zero norm.
    """
    if dim is None:
        dim = config.EMBEDDING_DIM
    a = struct.unpack(f"{dim}f", vec_a_bytes)
    b = struct.unpack(f"{dim}f", vec_b_bytes)
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Per-file affinity computation
# ---------------------------------------------------------------------------


def compute_file_icor_affinity(
    file_path: str,
    db_path: Path | None = None,
) -> list[tuple[str, float]]:
    """Compute ICOR dimension affinities for a single vault file.

    Retrieves the file's embedding from ``vec_vault`` and compares it
    against every ICOR reference embedding in ``vec_icor``. For each
    dimension, the *maximum* cosine similarity across all of that
    dimension's reference texts is used as the affinity score.

    Args:
        file_path: Relative path within the vault (e.g. ``"Daily Notes/2026-03-06.md"``).
        db_path: Optional override for the database path.

    Returns:
        List of ``(dimension_name, score)`` tuples for scores
        >= ``ICOR_AFFINITY_THRESHOLD``, sorted by score descending.
        Returns ``[]`` if embeddings are unavailable or the file is not
        yet embedded.
    """
    # Skip non-knowledge files
    if any(file_path.startswith(prefix) for prefix in _AFFINITY_SKIP_PREFIXES):
        return []

    try:
        from core.embedding_store import get_file_embedding, get_icor_embeddings
    except ImportError:
        logger.debug("embedding_store not available — skipping ICOR affinity")
        return []

    file_emb = get_file_embedding(file_path, db_path=db_path)
    if file_emb is None:
        return []

    icor_embeddings = get_icor_embeddings(db_path=db_path)
    if not icor_embeddings:
        return []

    dim = config.EMBEDDING_DIM
    results: list[tuple[str, float]] = []

    for dimension, ref_emb_list in icor_embeddings.items():
        max_sim = 0.0
        for ref_emb in ref_emb_list:
            try:
                sim = _cosine_similarity(file_emb, ref_emb, dim=dim)
                if sim > max_sim:
                    max_sim = sim
            except (struct.error, ValueError):
                # Corrupted or wrong-size embedding — skip this reference
                continue

        if max_sim >= ICOR_AFFINITY_THRESHOLD:
            results.append((dimension, max_sim))

    # Sort by score descending, apply Top-K limit
    results.sort(key=lambda t: t[1], reverse=True)
    return results[:ICOR_AFFINITY_TOP_K]


# ---------------------------------------------------------------------------
# Edge management
# ---------------------------------------------------------------------------


def update_icor_edges_for_file(
    file_path: str,
    db_path: Path | None = None,
) -> int:
    """Update ICOR affinity edges for a single vault file.

    1. Look up the file's node in ``vault_nodes``.
    2. Delete existing ``icor_affinity`` edges originating from that node.
    3. Compute affinities via :func:`compute_file_icor_affinity`.
    4. For each qualifying dimension, create an ``icor_affinity`` edge
       from the document node to the ICOR dimension node.

    Args:
        file_path: Relative path within the vault.
        db_path: Optional override for the database path.

    Returns:
        Number of ICOR affinity edges created.
    """
    from core.graph_ops import (
        delete_edges_for_node,
        get_node_by_path,
        get_node_by_title,
        upsert_edge,
    )

    node = get_node_by_path(file_path, db_path=db_path)
    if node is None:
        logger.debug("No vault_node for %s — skipping ICOR edge update", file_path)
        return 0

    node_id = node["id"]

    # Remove stale icor_affinity edges
    delete_edges_for_node(node_id, edge_type="icor_affinity", direction="outgoing", db_path=db_path)

    # Compute affinities
    affinities = compute_file_icor_affinity(file_path, db_path=db_path)
    if not affinities:
        return 0

    edge_count = 0
    for dimension, score in affinities:
        icor_node = get_node_by_title(dimension, db_path=db_path)
        if icor_node is None:
            logger.debug(
                "ICOR dimension node '%s' not found — skipping edge from %s",
                dimension,
                file_path,
            )
            continue

        upsert_edge(
            source_id=node_id,
            target_id=icor_node["id"],
            edge_type="icor_affinity",
            weight=score,
            db_path=db_path,
        )
        edge_count += 1

    if edge_count:
        logger.debug(
            "Created %d ICOR affinity edges for %s (top: %s %.2f)",
            edge_count,
            file_path,
            affinities[0][0],
            affinities[0][1],
        )

    return edge_count


# ---------------------------------------------------------------------------
# Bulk rebuild
# ---------------------------------------------------------------------------


def rebuild_all_icor_edges(db_path: Path | None = None) -> int:
    """Rebuild ICOR affinity edges for every document node in the graph.

    Steps:
    1. Ensure the 6 ICOR dimension nodes exist.
    2. Query all document nodes from ``vault_nodes``.
    3. For each document, call :func:`update_icor_edges_for_file`.

    This is designed to run at startup or during a full reindex.

    Args:
        db_path: Optional override for the database path.

    Returns:
        Total number of ICOR affinity edges created across all files.
    """
    from core.graph_ops import ensure_icor_nodes

    # Ensure ICOR dimension nodes are present
    ensure_icor_nodes(db_path=db_path)

    # Get all document nodes
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT file_path FROM vault_nodes WHERE node_type = 'document'"
        ).fetchall()

    file_paths = [row["file_path"] for row in rows]

    if not file_paths:
        logger.info("No document nodes found — skipping ICOR edge rebuild")
        return 0

    total = 0
    for fp in file_paths:
        try:
            total += update_icor_edges_for_file(fp, db_path=db_path)
        except Exception:
            logger.debug("ICOR edge update failed for %s", fp, exc_info=True)

    logger.info(
        "Rebuilt ICOR affinity edges: %d edges across %d files",
        total,
        len(file_paths),
    )
    return total

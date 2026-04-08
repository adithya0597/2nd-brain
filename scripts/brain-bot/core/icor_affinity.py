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
import json as _json
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
ICOR_AFFINITY_THRESHOLD = 0.58
ICOR_AFFINITY_TOP_K = 3  # Keep at most top-K dimensions per file

# Prefixes for files that should be skipped (non-knowledge content)
_AFFINITY_SKIP_PREFIXES = ("Templates/", "Identity/", "CLAUDE")

# ---------------------------------------------------------------------------
# Frontmatter-based ICOR classification (overrides embedding similarity)
# ---------------------------------------------------------------------------

_VALID_DIMENSIONS = {
    "Health & Vitality", "Wealth & Finance", "Relationships",
    "Mind & Growth", "Purpose & Impact", "Systems & Environment",
}

# Maps key element / tag names (lowercase) to their parent ICOR dimension
_ELEMENT_TO_DIMENSION = {
    "fitness": "Health & Vitality",
    "nutrition": "Health & Vitality",
    "sleep": "Health & Vitality",
    "mental health": "Health & Vitality",
    "income": "Wealth & Finance",
    "investments": "Wealth & Finance",
    "budgeting": "Wealth & Finance",
    "career": "Wealth & Finance",
    "family": "Relationships",
    "friendships": "Relationships",
    "professional network": "Relationships",
    "romantic": "Relationships",
    "learning": "Mind & Growth",
    "creativity": "Mind & Growth",
    "mindfulness": "Mind & Growth",
    "reading": "Mind & Growth",
    "mission": "Purpose & Impact",
    "volunteering": "Purpose & Impact",
    "legacy": "Purpose & Impact",
    "community": "Purpose & Impact",
    "personal brand": "Purpose & Impact",
    "digital tools": "Systems & Environment",
    "physical spaces": "Systems & Environment",
    "routines": "Systems & Environment",
    "automation": "Systems & Environment",
    "side projects": "Systems & Environment",
}


def _resolve_frontmatter_dimensions(fm: dict) -> list[str]:
    """Extract ICOR dimensions from frontmatter icor_elements/icor_tag.

    Returns list of dimension names (deduped, order preserved).
    Empty list if no explicit dimensions found.
    """
    dims: list[str] = []
    seen: set[str] = set()

    for elem in (fm.get("icor_elements") or []):
        if elem in _VALID_DIMENSIONS and elem not in seen:
            dims.append(elem)
            seen.add(elem)
            continue
        dim = _ELEMENT_TO_DIMENSION.get(elem.lower().strip())
        if dim and dim not in seen:
            dims.append(dim)
            seen.add(dim)

    icor_tag = fm.get("icor_tag")
    if icor_tag:
        if icor_tag in _VALID_DIMENSIONS and icor_tag not in seen:
            dims.append(icor_tag)
            seen.add(icor_tag)
        else:
            dim = _ELEMENT_TO_DIMENSION.get(icor_tag.lower().strip())
            if dim and dim not in seen:
                dims.append(dim)
                seen.add(dim)

    return dims


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

    # Frontmatter override: explicit tags trump embedding similarity
    resolved_db = db_path or config.DB_PATH
    with get_connection(resolved_db, row_factory=sqlite3.Row) as conn:
        fm_row = conn.execute(
            "SELECT frontmatter_json FROM vault_nodes WHERE file_path = ?",
            (file_path,),
        ).fetchone()

    if fm_row:
        try:
            fm = _json.loads(fm_row["frontmatter_json"] or "{}")
        except (ValueError, TypeError):
            fm = {}
        explicit_dims = _resolve_frontmatter_dimensions(fm)
        if explicit_dims:
            return [(dim, 1.0) for dim in explicit_dims[:ICOR_AFFINITY_TOP_K]]

    # Fall through to embedding-based affinity
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

    # Sort by score descending, apply Top-K limit with gap pruning.
    # Secondary dimensions must score within 90% of the top dimension
    # to avoid weak spurious edges.
    results.sort(key=lambda t: t[1], reverse=True)
    if not results:
        return []

    top_score = results[0][1]
    gap_floor = top_score * 0.90
    pruned = [results[0]]
    for dim, score in results[1:ICOR_AFFINITY_TOP_K]:
        if score >= gap_floor:
            pruned.append((dim, score))
    return pruned


# ---------------------------------------------------------------------------
# Edge management
# ---------------------------------------------------------------------------


def update_icor_edges_for_file(
    file_path: str,
    db_path: Path | None = None,
) -> int:
    """Update ICOR affinity edges for a single vault file.

    1. Look up the file's node in ``vault_nodes``.
    2. Compute affinities via :func:`compute_file_icor_affinity`.
    3. Resolve dimension node IDs.
    4. Delete old + insert new edges in a single transaction.

    Computation happens before deletion so that a failure preserves
    the existing edges.

    Args:
        file_path: Relative path within the vault.
        db_path: Optional override for the database path.

    Returns:
        Number of ICOR affinity edges created.
    """
    from core.graph_ops import get_node_by_path, get_node_by_title

    node = get_node_by_path(file_path, db_path=db_path)
    if node is None:
        logger.debug("No vault_node for %s — skipping ICOR edge update", file_path)
        return 0

    node_id = node["id"]

    # Compute affinities BEFORE deleting (preserves old edges on failure)
    affinities = compute_file_icor_affinity(file_path, db_path=db_path)

    # Resolve dimension node IDs
    edges_to_create = []
    for dimension, score in affinities:
        icor_node = get_node_by_title(dimension, db_path=db_path)
        if icor_node is None:
            logger.debug(
                "ICOR dimension node '%s' not found — skipping edge from %s",
                dimension,
                file_path,
            )
            continue
        edges_to_create.append((icor_node["id"], score))

    # Single transaction: delete old + insert new
    resolved = db_path or config.DB_PATH
    with get_connection(resolved) as conn:
        conn.execute(
            "DELETE FROM vault_edges WHERE source_node_id = ? AND edge_type = 'icor_affinity'",
            (node_id,),
        )
        for target_id, score in edges_to_create:
            conn.execute(
                """INSERT INTO vault_edges (source_node_id, target_node_id, edge_type, weight, metadata_json, verified_at)
                   VALUES (?, ?, 'icor_affinity', ?, '{}', datetime('now'))
                   ON CONFLICT(source_node_id, target_node_id, edge_type) DO UPDATE SET
                       weight = excluded.weight, verified_at = datetime('now')""",
                (node_id, target_id, score),
            )
        conn.commit()

    if edges_to_create:
        logger.debug("Created %d ICOR affinity edges for %s", len(edges_to_create), file_path)
    return len(edges_to_create)


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

    # Get all document nodes (exclude bot-generated content)
    with get_connection(db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            "SELECT file_path FROM vault_nodes "
            "WHERE node_type = 'document' AND type NOT IN ('report', 'inbox')"
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

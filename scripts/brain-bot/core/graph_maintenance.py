"""Proactive graph maintenance: orphan detection, connection suggestions, density tracking.

Pure business logic — no Telegram imports. Uses core.db_ops for async SQL
and core.embedding_store for vector similarity suggestions.
"""
import logging
from datetime import datetime
from pathlib import Path

import config
from core.db_connection import get_connection

logger = logging.getLogger(__name__)


def _dict_factory(cursor, row):
    """sqlite3.Row-like dict factory for raw connections."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _query_sync(sql: str, params: tuple = (), db_path: Path = None) -> list[dict]:
    """Run a synchronous SELECT query and return results as list of dicts."""
    with get_connection(db_path, row_factory=_dict_factory) as conn:
        rows = conn.execute(sql, params).fetchall()
        return rows


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

def find_orphan_documents(db_path: Path = None) -> list[dict]:
    """Find document nodes with no incoming edges of connection types.

    Returns list of dicts with keys: id, file_path, title, type, last_modified.
    """
    sql = """
        SELECT n.id, n.file_path, n.title, n.type, n.last_modified
        FROM vault_nodes n
        WHERE n.node_type = 'document'
          AND n.id NOT IN (
            SELECT DISTINCT target_node_id FROM vault_edges
            WHERE edge_type IN ('wikilink', 'tag_shared', 'semantic_similarity')
          )
          AND n.id NOT IN (
            SELECT DISTINCT source_node_id FROM vault_edges
            WHERE edge_type IN ('wikilink', 'tag_shared', 'semantic_similarity')
          )
        ORDER BY n.last_modified DESC
    """
    return _query_sync(sql, db_path=db_path)


# ---------------------------------------------------------------------------
# Connection suggestions
# ---------------------------------------------------------------------------

def suggest_connections_for_orphan(
    orphan_title: str,
    top_k: int = 3,
    db_path: Path = None,
) -> list[dict]:
    """Suggest potential connections for an orphan node using embedding similarity.

    Uses embedding_store.search_similar to find semantically close vault files.
    Filters out the orphan itself from results.

    Returns list of dicts: [{file_path, title, similarity_score}].
    """
    try:
        from core.embedding_store import search_similar
        results = search_similar(orphan_title, limit=top_k + 1, db_path=db_path)
    except Exception:
        logger.debug("Embedding search unavailable for suggestions", exc_info=True)
        return []

    suggestions = []
    for r in results:
        # Filter out self-match (title matches orphan title)
        if r.get("title", "").lower() == orphan_title.lower():
            continue
        suggestions.append({
            "file_path": r.get("file_path", ""),
            "title": r.get("title", ""),
            "similarity_score": round(1.0 - r.get("distance", 1.0), 3),
        })
        if len(suggestions) >= top_k:
            break

    return suggestions


# ---------------------------------------------------------------------------
# Stale concepts
# ---------------------------------------------------------------------------

def find_stale_concepts(days: int = 60, db_path: Path = None) -> list[dict]:
    """Find document nodes not modified in the given number of days.

    Returns list of dicts: [{file_path, title, last_modified, days_stale}].
    """
    sql = """
        SELECT n.file_path, n.title, n.last_modified,
               CAST(julianday('now') - julianday(n.last_modified) AS INTEGER) AS days_stale
        FROM vault_nodes n
        WHERE n.node_type = 'document'
          AND n.last_modified < date('now', ? || ' days')
        ORDER BY n.last_modified ASC
        LIMIT 20
    """
    return _query_sync(sql, (f"-{days}",), db_path=db_path)


# ---------------------------------------------------------------------------
# Graph density
# ---------------------------------------------------------------------------

def compute_graph_density(db_path: Path = None) -> dict:
    """Compute graph density for document-to-document edges.

    Returns dict with keys: node_count, edge_count, density, target_density.
    Handles edge case of 0 or 1 nodes (density = 0).
    """
    node_sql = """
        SELECT COUNT(*) AS cnt FROM vault_nodes WHERE node_type = 'document'
    """
    edge_sql = """
        SELECT COUNT(*) AS cnt FROM vault_edges
        WHERE edge_type IN ('wikilink', 'tag_shared', 'semantic_similarity')
    """
    nodes = _query_sync(node_sql, db_path=db_path)
    edges = _query_sync(edge_sql, db_path=db_path)

    node_count = nodes[0]["cnt"] if nodes else 0
    edge_count = edges[0]["cnt"] if edges else 0

    if node_count <= 1:
        density = 0.0
    else:
        # Density for undirected graph: 2 * E / (N * (N - 1))
        density = (2 * edge_count) / (node_count * (node_count - 1))

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "density": round(density, 6),
        "target_density": 0.05,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_maintenance(db_path: Path = None) -> dict:
    """Run full graph maintenance analysis.

    Calls all detection functions, enriches orphans with suggestions.
    Returns a dict with keys: orphans, stale_concepts, density, timestamp.
    Performance target: <10s for a 500-file vault.
    """
    db_path = db_path or config.DB_PATH

    # 1. Find orphans (cap at 10 for performance)
    all_orphans = find_orphan_documents(db_path=db_path)
    orphans_with_suggestions = []
    for orphan in all_orphans[:10]:
        suggestions = suggest_connections_for_orphan(
            orphan.get("title", ""),
            top_k=3,
            db_path=db_path,
        )
        orphans_with_suggestions.append({
            **orphan,
            "suggestions": suggestions,
        })

    # 2. Stale concepts
    stale = find_stale_concepts(days=60, db_path=db_path)

    # 3. Graph density
    density = compute_graph_density(db_path=db_path)

    return {
        "orphans": orphans_with_suggestions,
        "stale_concepts": stale,
        "density": density,
        "total_orphans": len(all_orphans),
        "timestamp": datetime.now().isoformat(),
    }

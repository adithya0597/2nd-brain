"""Metadata filtering for vector search via SQL CTEs.

sqlite-vec doesn't support WHERE clauses on vec0 virtual tables
during KNN search. This module builds CTE pre-filters that narrow
the search space before expensive embedding comparison.

Supported filters:
- date_range: (start_date, end_date) for vault_nodes.last_modified
- dimensions: list of ICOR dimension names (via icor_affinity edges)
- file_types: list of vault_nodes.type values (journal, concept, etc.)
- community_id: specific community cluster ID
- node_type: vault_nodes.node_type (default: 'document')
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class MetadataFilters:
    """Search metadata filters.

    All fields are optional. None means no filter applied.
    """
    date_range: tuple[str, str] | None = None  # (start_date, end_date) ISO format
    dimensions: list[str] | None = None  # ICOR dimension names
    file_types: list[str] | None = None  # vault_nodes.type values
    community_id: int | None = None
    node_type: str = "document"  # Default to real documents only


def is_selective(filters: MetadataFilters | None) -> bool:
    """Heuristic: is the filter selective enough to justify CTE overhead?

    Returns True if estimated selectivity < 70% (worth pre-filtering).
    """
    if filters is None:
        return False

    # Date range is always selective (typically 1-30 days out of 365)
    if filters.date_range is not None:
        return True

    # 1-2 dimensions out of 6 = 17-33% selectivity
    if filters.dimensions and len(filters.dimensions) <= 3:
        return True

    # 1-2 file types out of 5 = 20-40% selectivity
    if filters.file_types and len(filters.file_types) <= 2:
        return True

    # Single community out of 5-10 = 10-20% selectivity
    if filters.community_id is not None:
        return True

    return False


def build_filter_cte(filters: MetadataFilters) -> tuple[str, list]:
    """Build a SQL CTE that pre-filters vault_nodes by metadata.

    Returns:
        (cte_sql, params) where cte_sql starts with "WITH filtered_docs AS (...)"
        and params are the bind parameters.

    The CTE produces a set of file_paths that match ALL filter criteria.
    Use with: INNER JOIN filtered_docs ON vec_table.file_path = filtered_docs.file_path
    """
    where_clauses = []
    params = []

    # Always filter to target node_type
    where_clauses.append("vn.node_type = ?")
    params.append(filters.node_type)

    # Date range filter
    if filters.date_range:
        start_date, end_date = filters.date_range
        where_clauses.append("vn.last_modified >= ?")
        params.append(start_date)
        where_clauses.append("vn.last_modified <= ?")
        params.append(end_date)

    # File type filter
    if filters.file_types:
        placeholders = ", ".join("?" for _ in filters.file_types)
        where_clauses.append(f"vn.type IN ({placeholders})")
        params.extend(filters.file_types)

    # Community filter
    if filters.community_id is not None:
        where_clauses.append("vn.community_id = ?")
        params.append(filters.community_id)

    # ICOR dimension filter (via icor_affinity edges)
    dimension_join = ""
    if filters.dimensions:
        dim_placeholders = ", ".join("?" for _ in filters.dimensions)
        dimension_join = f"""
            AND EXISTS (
                SELECT 1 FROM vault_edges e
                JOIN vault_nodes vn_dim ON e.target_node_id = vn_dim.id
                WHERE e.source_node_id = vn.id
                AND e.edge_type = 'icor_affinity'
                AND vn_dim.title IN ({dim_placeholders})
            )
        """
        params.extend(filters.dimensions)

    where_sql = " AND ".join(where_clauses)

    cte = f"""WITH filtered_docs AS (
        SELECT vn.file_path
        FROM vault_nodes vn
        WHERE {where_sql}
        {dimension_join}
    )"""

    return cte, params


def build_filtered_vec_query(
    vec_table: str,
    filters: MetadataFilters,
    k: int = 20
) -> tuple[str, list]:
    """Build complete filtered vector search query.

    Args:
        vec_table: "vec_vault" or "vec_vault_chunks"
        filters: MetadataFilters to apply
        k: Number of KNN results

    Returns:
        (full_sql, params) ready to execute with embedding bytes prepended.
        The embedding MATCH parameter should be passed as params[0].
    """
    cte, cte_params = build_filter_cte(filters)

    query = f"""{cte}
    SELECT v.rowid, v.distance, v.file_path, v.title
    FROM {vec_table} v
    INNER JOIN filtered_docs ON v.file_path = filtered_docs.file_path
    WHERE v.embedding MATCH ? AND k = ?
    ORDER BY v.distance"""

    # Params order: CTE params come first (processed in WITH clause),
    # then embedding_bytes and k for the main query.
    # The caller prepends embedding_bytes and appends k.
    return query, cte_params


def filters_for_command(command_name: str) -> MetadataFilters | None:
    """Return default metadata filters for a given brain command.

    Commands have different search contexts:
    - find: Recent, high-quality concepts and projects
    - today: Last 7 days, all types
    - drift: Last 60 days, journal only
    - trace: No filters (full history)
    - ideas: Last 30 days, all types
    - emerge: Last 14 days, all types
    """
    now = datetime.now()

    COMMAND_FILTERS = {
        "find": MetadataFilters(
            date_range=(
                (now - timedelta(days=90)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
            ),
            file_types=["concept", "project", "journal"],
        ),
        "today": MetadataFilters(
            date_range=(
                (now - timedelta(days=7)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
            ),
        ),
        "drift": MetadataFilters(
            date_range=(
                (now - timedelta(days=60)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
            ),
            file_types=["journal"],
        ),
        "ideas": MetadataFilters(
            date_range=(
                (now - timedelta(days=30)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
            ),
        ),
        "emerge": MetadataFilters(
            date_range=(
                (now - timedelta(days=14)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
            ),
        ),
        # trace, connect, challenge, ghost: no filters (full history)
    }

    return COMMAND_FILTERS.get(command_name)

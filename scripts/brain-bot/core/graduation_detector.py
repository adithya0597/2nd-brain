"""Detect recurring themes in captures eligible for concept graduation."""
import hashlib
import json
import logging

from core.db_ops import query

logger = logging.getLogger(__name__)


async def detect_graduation_candidates(db_path=None) -> list[dict]:
    """Find dimensions appearing 3+ times across 7+ days with no existing concept.

    Uses pure SQL frequency counting on captures_log with json_each() to
    unpack dimensions_json. NO DBSCAN, NO scikit-learn -- leverages existing
    classification data.

    Returns max 3 candidates:
        [{proposed_title, dimension, source_ids, source_texts,
          days_span, capture_count, cluster_hash}]
    """
    # Step 1: Find dimensions with recurring captures (3+ times, 7+ day spread)
    candidates = await query(
        """
        SELECT
            d.value AS dimension,
            COUNT(DISTINCT cl.id) AS capture_count,
            COUNT(DISTINCT date(cl.created_at)) AS distinct_days,
            MIN(cl.created_at) AS first_seen,
            MAX(cl.created_at) AS last_seen,
            CAST(julianday(MAX(cl.created_at)) - julianday(MIN(cl.created_at)) AS INTEGER) AS days_span,
            GROUP_CONCAT(cl.id) AS capture_ids,
            GROUP_CONCAT(SUBSTR(cl.message_text, 1, 100), ' | ') AS preview_texts
        FROM captures_log cl, json_each(cl.dimensions_json) d
        WHERE cl.created_at >= date('now', '-30 days')
          AND cl.confidence >= 0.5
        GROUP BY d.value
        HAVING capture_count >= 3 AND distinct_days >= 7
        ORDER BY capture_count DESC
        LIMIT 5
        """,
        db_path=db_path,
    )

    if not candidates:
        return []

    # Step 2: Filter out dimensions that already have concept notes
    existing_concepts = await query(
        "SELECT DISTINCT icor_elements FROM concept_metadata WHERE status != 'archived'",
        db_path=db_path,
    )
    existing_dims = set()
    for row in existing_concepts:
        try:
            elements = json.loads(row.get("icor_elements", "[]"))
            existing_dims.update(elements)
        except (json.JSONDecodeError, TypeError):
            pass

    # Step 3: Filter out already-proposed (pending/snoozed/rejected) clusters
    pending = await query(
        "SELECT cluster_hash FROM graduation_proposals "
        "WHERE status IN ('pending', 'snoozed', 'rejected')",
        db_path=db_path,
    )
    pending_hashes = {row["cluster_hash"] for row in pending}

    # Step 4: Build final candidate list
    results = []
    for row in candidates:
        dim = row.get("dimension", "")
        if dim in existing_dims:
            continue

        capture_ids = row.get("capture_ids", "").split(",")
        cluster_hash = hashlib.md5("|".join(sorted(capture_ids)).encode()).hexdigest()

        if cluster_hash in pending_hashes:
            continue

        results.append({
            "proposed_title": f"{dim} Insights",
            "dimension": dim,
            "source_ids": capture_ids,
            "source_texts": row.get("preview_texts", "").split(" | "),
            "days_span": row.get("days_span", 0),
            "capture_count": row.get("capture_count", 0),
            "cluster_hash": cluster_hash,
        })

        if len(results) >= 3:
            break

    return results

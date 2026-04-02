"""Daily engagement metrics engine.

Queries existing tables to compute a daily snapshot of user activity across
captures, actions, journal entries, vault changes, and Notion syncs. Stores
results in the ``engagement_daily`` table for trend analysis and Brain Level
computation.

Schema lives in migrate-db.py (step 22a) and conftest.py.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta

from core.db_connection import get_connection

logger = logging.getLogger(__name__)

_ICOR_DIMENSIONS = [
    "Health & Vitality",
    "Wealth & Finance",
    "Relationships",
    "Mind & Growth",
    "Purpose & Impact",
    "Systems & Environment",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_daily_metrics(date_str: str = None, db_path=None) -> dict:
    """Compute all engagement metrics for a given date.

    Args:
        date_str: Date in YYYY-MM-DD format. Defaults to today.
        db_path: Optional override for the database path.

    Returns:
        A dict matching the ``engagement_daily`` table columns.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    day_start = date_str + " 00:00:00"
    day_end = date_str + " 23:59:59"

    with get_connection(db_path=db_path) as conn:
        # -- Captures --
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, "
            "COALESCE(SUM(is_actionable), 0) AS actionable "
            "FROM captures_log "
            "WHERE created_at BETWEEN ? AND ?",
            (day_start, day_end),
        ).fetchone()
        captures_count = row[0]
        actionable_captures = row[1]

        # -- Action items --
        actions_created = conn.execute(
            "SELECT COUNT(*) FROM action_items WHERE source_date = ?",
            (date_str,),
        ).fetchone()[0]

        actions_completed = conn.execute(
            "SELECT COUNT(*) FROM action_items "
            "WHERE completed_at BETWEEN ? AND ?",
            (day_start, day_end),
        ).fetchone()[0]

        actions_pending = conn.execute(
            "SELECT COUNT(*) FROM action_items WHERE status = 'pending'",
        ).fetchone()[0]

        # -- Journal entries (aggregates) --
        agg_row = conn.execute(
            "SELECT COUNT(*) AS cnt, "
            "COALESCE(SUM(LENGTH(content)), 0) AS total_chars, "
            "COALESCE(AVG(sentiment_score), 0.0) AS avg_sent "
            "FROM journal_entries WHERE date = ?",
            (date_str,),
        ).fetchone()

        journal_entry_count = agg_row[0]
        # Approximate word count: ~5 chars per word
        journal_word_count = agg_row[1] // 5 if agg_row[1] else 0
        avg_sentiment = round(agg_row[2], 4) if agg_row[2] else 0.0

        # Mood/energy from the latest entry of the day
        me_row = conn.execute(
            "SELECT mood, energy FROM journal_entries "
            "WHERE date = ? ORDER BY created_at DESC LIMIT 1",
            (date_str,),
        ).fetchone()
        mood = me_row[0] if me_row and me_row[0] else None
        energy = me_row[1] if me_row and me_row[1] else None

        # -- Dimension mentions (from captures_log.dimensions_json) --
        dimension_mentions = {d: 0 for d in _ICOR_DIMENSIONS}
        cap_rows = conn.execute(
            "SELECT dimensions_json FROM captures_log "
            "WHERE created_at BETWEEN ? AND ? "
            "AND dimensions_json IS NOT NULL AND dimensions_json != '[]'",
            (day_start, day_end),
        ).fetchall()
        for cap_row in cap_rows:
            try:
                dims = json.loads(cap_row[0])
                if isinstance(dims, list):
                    for d in dims:
                        if isinstance(d, str) and d in dimension_mentions:
                            dimension_mentions[d] += 1
                elif isinstance(dims, dict):
                    for d, v in dims.items():
                        if d in dimension_mentions:
                            dimension_mentions[d] += (
                                v if isinstance(v, int) else 1
                            )
            except (json.JSONDecodeError, TypeError):
                continue

        dimension_mentions_json = json.dumps(dimension_mentions)

        # -- Vault activity --
        vault_files_modified = conn.execute(
            "SELECT COUNT(*) FROM vault_nodes "
            "WHERE indexed_at BETWEEN ? AND ?",
            (day_start, day_end),
        ).fetchone()[0]

        vault_files_created = conn.execute(
            "SELECT COUNT(*) FROM vault_nodes "
            "WHERE indexed_at BETWEEN ? AND ? AND type != ''",
            (day_start, day_end),
        ).fetchone()[0]

        # -- Edges created --
        edges_created = conn.execute(
            "SELECT COUNT(*) FROM vault_edges "
            "WHERE created_at BETWEEN ? AND ?",
            (day_start, day_end),
        ).fetchone()[0]

        # -- Notion items synced --
        notion_items_synced = conn.execute(
            "SELECT COUNT(*) FROM sync_outbox "
            "WHERE status = 'confirmed' "
            "AND confirmed_at BETWEEN ? AND ?",
            (day_start, day_end),
        ).fetchone()[0]

    # -- Engagement score (0-10) --
    journaled = 2.0 if journal_entry_count > 0 else 0.0
    captures_score = min(captures_count / 5 * 2, 2.0)
    actions_score = min(actions_completed / 3 * 2, 2.0) if actions_completed else 0.0
    active_dims = len(
        [d for d in dimension_mentions if dimension_mentions[d] > 0]
    )
    breadth = min(active_dims / 3 * 2, 2.0)
    vault_score = min(
        (vault_files_modified + vault_files_created) / 5 * 2, 2.0
    )
    engagement_score = round(
        min(journaled + captures_score + actions_score + breadth + vault_score, 10.0),
        2,
    )

    return {
        "date": date_str,
        "captures_count": captures_count,
        "actionable_captures": actionable_captures,
        "actions_created": actions_created,
        "actions_completed": actions_completed,
        "actions_pending": actions_pending,
        "journal_entry_count": journal_entry_count,
        "journal_word_count": journal_word_count,
        "avg_sentiment": avg_sentiment,
        "mood": mood,
        "energy": energy,
        "dimension_mentions_json": dimension_mentions_json,
        "vault_files_modified": vault_files_modified,
        "vault_files_created": vault_files_created,
        "edges_created": edges_created,
        "notion_items_synced": notion_items_synced,
        "engagement_score": engagement_score,
    }


def save_daily_metrics(metrics: dict, db_path=None) -> None:
    """Persist a metrics snapshot to the ``engagement_daily`` table.

    Uses INSERT OR REPLACE so calling twice for the same date is safe.
    """
    with get_connection(db_path=db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO engagement_daily (
                date, captures_count, actionable_captures,
                actions_created, actions_completed, actions_pending,
                journal_entry_count, journal_word_count,
                avg_sentiment, mood, energy,
                dimension_mentions_json,
                vault_files_modified, vault_files_created,
                edges_created, notion_items_synced,
                engagement_score, computed_at
            ) VALUES (
                :date, :captures_count, :actionable_captures,
                :actions_created, :actions_completed, :actions_pending,
                :journal_entry_count, :journal_word_count,
                :avg_sentiment, :mood, :energy,
                :dimension_mentions_json,
                :vault_files_modified, :vault_files_created,
                :edges_created, :notion_items_synced,
                :engagement_score, datetime('now')
            )
            """,
            metrics,
        )
        conn.commit()


def backfill_engagement(days: int = 30, db_path=None) -> int:
    """Compute and save metrics for the last *days* days.

    Skips dates whose ``computed_at`` is within the last hour to avoid
    redundant re-computation of fresh data.

    Returns:
        The number of days actually processed.
    """
    today = datetime.now().date()
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    processed = 0

    with get_connection(db_path=db_path) as conn:
        for offset in range(days, -1, -1):
            d = (today - timedelta(days=offset)).isoformat()

            # Check if already computed recently
            row = conn.execute(
                "SELECT computed_at FROM engagement_daily WHERE date = ?",
                (d,),
            ).fetchone()
            if row and row[0] and row[0] >= one_hour_ago:
                continue

    # Compute outside the check-connection to avoid holding it open
    # during potentially many iterations
    dates_to_compute = []
    with get_connection(db_path=db_path) as conn:
        for offset in range(days, -1, -1):
            d = (today - timedelta(days=offset)).isoformat()
            row = conn.execute(
                "SELECT computed_at FROM engagement_daily WHERE date = ?",
                (d,),
            ).fetchone()
            if row and row[0] and row[0] >= one_hour_ago:
                continue
            dates_to_compute.append(d)

    for d in dates_to_compute:
        metrics = compute_daily_metrics(d, db_path=db_path)
        save_daily_metrics(metrics, db_path=db_path)
        processed += 1

    return processed


def get_engagement_history(days: int = 7, db_path=None) -> list[dict]:
    """Return the last *days* engagement snapshots, most recent first.

    Returns:
        A list of dicts (one per day with data), ordered by date DESC.
    """
    with get_connection(db_path=db_path, row_factory=sqlite3.Row) as conn:
        cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            "SELECT * FROM engagement_daily "
            "WHERE date >= ? "
            "ORDER BY date DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

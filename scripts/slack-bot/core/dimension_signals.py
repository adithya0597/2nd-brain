"""Dimension momentum signals and Brain Level scoring engine.

Computes per-dimension daily momentum (hot/warm/cold/frozen), trend analysis
(rising/stable/declining), and a monthly aggregate Brain Level (1-10) from
engagement data across captures, journal entries, actions, and vault activity.

Schema lives in migrate-db.py (step 22b, 22c) and conftest.py.
"""

import calendar
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
# Momentum & Trend Classifiers
# ---------------------------------------------------------------------------


def classify_momentum(touchpoints_7d: int) -> str:
    """Classify a dimension's 7-day momentum level.

    Args:
        touchpoints_7d: Total touchpoints (mentions + captures + actions)
            over the last 7 days.

    Returns:
        One of 'hot', 'warm', 'cold', 'frozen'.
    """
    if touchpoints_7d >= 10:
        return "hot"
    elif touchpoints_7d >= 4:
        return "warm"
    elif touchpoints_7d >= 1:
        return "cold"
    else:
        return "frozen"


def classify_trend(current_7d: int, previous_7d: int) -> str:
    """Classify the trend direction between two 7-day windows.

    Args:
        current_7d: Touchpoints in the most recent 7-day window.
        previous_7d: Touchpoints in the prior 7-day window (days -14 to -7).

    Returns:
        One of 'rising', 'stable', 'declining'.
    """
    if previous_7d == 0:
        return "rising" if current_7d > 0 else "stable"

    ratio = current_7d / previous_7d
    if ratio >= 1.3:
        return "rising"
    elif ratio <= 0.7:
        return "declining"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Dimension Signals
# ---------------------------------------------------------------------------


def compute_dimension_signals(date_str: str = None, db_path=None) -> list[dict]:
    """Compute momentum signals for all 6 ICOR dimensions on a given date.

    For each dimension, gathers daily captures, journal mentions, and action
    items, then computes rolling 7-day and 30-day aggregates, momentum
    classification, and trend direction.

    Args:
        date_str: Date in YYYY-MM-DD format. Defaults to today.
        db_path: Optional override for the database path.

    Returns:
        A list of 6 dicts (one per dimension) matching the
        ``dimension_signals`` table columns.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    day_start = date_str + " 00:00:00"
    day_end = date_str + " 23:59:59"

    # Rolling window boundaries
    seven_days_ago = (target_date - timedelta(days=6)).isoformat()
    fourteen_days_ago = (target_date - timedelta(days=13)).isoformat()
    eight_days_ago = (target_date - timedelta(days=7)).isoformat()
    thirty_days_ago = (target_date - timedelta(days=29)).isoformat()

    results = []

    with get_connection(db_path=db_path) as conn:
        for dim in _ICOR_DIMENSIONS:
            # --- Day-level metrics ---

            # 1. Captures for this dimension today
            cap_rows = conn.execute(
                "SELECT dimensions_json FROM captures_log "
                "WHERE created_at BETWEEN ? AND ? "
                "AND dimensions_json IS NOT NULL AND dimensions_json != '[]'",
                (day_start, day_end),
            ).fetchall()
            captures = 0
            for row in cap_rows:
                try:
                    dims = json.loads(row[0])
                    if isinstance(dims, list) and dim in dims:
                        captures += 1
                    elif isinstance(dims, dict) and dim in dims:
                        captures += dims[dim] if isinstance(dims[dim], int) else 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # 2. Journal mentions for this dimension today
            je_rows = conn.execute(
                "SELECT icor_elements FROM journal_entries WHERE date = ?",
                (date_str,),
            ).fetchall()
            mentions = 0
            for row in je_rows:
                try:
                    elements = json.loads(row[0]) if row[0] else []
                    if isinstance(elements, list):
                        for el in elements:
                            if isinstance(el, str) and dim.lower() in el.lower():
                                mentions += 1
                    elif isinstance(elements, str) and dim.lower() in elements.lower():
                        mentions += 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # 3. Actions for this dimension today
            actions_created = conn.execute(
                "SELECT COUNT(*) FROM action_items "
                "WHERE source_date = ? AND icor_element LIKE ?",
                (date_str, f"%{dim}%"),
            ).fetchone()[0]

            actions_completed = conn.execute(
                "SELECT COUNT(*) FROM action_items "
                "WHERE completed_at BETWEEN ? AND ? "
                "AND icor_element LIKE ?",
                (day_start, day_end, f"%{dim}%"),
            ).fetchone()[0]

            # --- Rolling 7-day metrics ---
            rolling_7d_mentions = _rolling_mentions(
                conn, dim, seven_days_ago, date_str
            )
            rolling_7d_captures = _rolling_captures(
                conn, dim, seven_days_ago, date_str
            )
            rolling_7d_actions = conn.execute(
                "SELECT COUNT(*) FROM action_items "
                "WHERE source_date BETWEEN ? AND ? "
                "AND icor_element LIKE ?",
                (seven_days_ago, date_str, f"%{dim}%"),
            ).fetchone()[0]

            # --- Rolling 30-day mentions ---
            rolling_30d_mentions = _rolling_mentions(
                conn, dim, thirty_days_ago, date_str
            )

            # --- Momentum and Trend ---
            touchpoints_7d = rolling_7d_mentions + rolling_7d_captures + rolling_7d_actions
            momentum = classify_momentum(touchpoints_7d)

            # Momentum score: normalized 0-10
            momentum_score = round(min(touchpoints_7d / 15 * 10, 10.0), 2)

            # Previous 7-day window for trend
            prev_7d_mentions = _rolling_mentions(
                conn, dim, fourteen_days_ago, eight_days_ago
            )
            prev_7d_captures = _rolling_captures(
                conn, dim, fourteen_days_ago, eight_days_ago
            )
            prev_7d_actions = conn.execute(
                "SELECT COUNT(*) FROM action_items "
                "WHERE source_date BETWEEN ? AND ? "
                "AND icor_element LIKE ?",
                (fourteen_days_ago, eight_days_ago, f"%{dim}%"),
            ).fetchone()[0]
            prev_touchpoints = prev_7d_mentions + prev_7d_captures + prev_7d_actions

            trend = classify_trend(touchpoints_7d, prev_touchpoints)

            signal = {
                "date": date_str,
                "dimension": dim,
                "mentions": mentions,
                "captures": captures,
                "actions_created": actions_created,
                "actions_completed": actions_completed,
                "rolling_7d_mentions": rolling_7d_mentions,
                "rolling_7d_captures": rolling_7d_captures,
                "rolling_30d_mentions": rolling_30d_mentions,
                "momentum": momentum,
                "momentum_score": momentum_score,
                "trend": trend,
            }
            results.append(signal)

            # Persist to DB
            conn.execute(
                """
                INSERT OR REPLACE INTO dimension_signals (
                    date, dimension, mentions, captures,
                    actions_created, actions_completed,
                    rolling_7d_mentions, rolling_7d_captures,
                    rolling_30d_mentions,
                    momentum, momentum_score, trend, computed_at
                ) VALUES (
                    :date, :dimension, :mentions, :captures,
                    :actions_created, :actions_completed,
                    :rolling_7d_mentions, :rolling_7d_captures,
                    :rolling_30d_mentions,
                    :momentum, :momentum_score, :trend, datetime('now')
                )
                """,
                signal,
            )

        conn.commit()

    return results


def _rolling_mentions(conn, dim: str, start_date: str, end_date: str) -> int:
    """Sum dimension mentions from engagement_daily.dimension_mentions_json
    and journal_entries.icor_elements over a date range."""
    total = 0

    # From engagement_daily (pre-computed)
    rows = conn.execute(
        "SELECT dimension_mentions_json FROM engagement_daily "
        "WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchall()
    for row in rows:
        try:
            dm = json.loads(row[0]) if row[0] else {}
            if isinstance(dm, dict) and dim in dm:
                total += dm[dim] if isinstance(dm[dim], int) else 0
        except (json.JSONDecodeError, TypeError):
            continue

    # Also check journal_entries directly (in case engagement_daily is not yet backfilled)
    je_rows = conn.execute(
        "SELECT icor_elements FROM journal_entries "
        "WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchall()
    for row in je_rows:
        try:
            elements = json.loads(row[0]) if row[0] else []
            if isinstance(elements, list):
                for el in elements:
                    if isinstance(el, str) and dim.lower() in el.lower():
                        total += 1
            elif isinstance(elements, str) and dim.lower() in elements.lower():
                total += 1
        except (json.JSONDecodeError, TypeError):
            continue

    return total


def _rolling_captures(conn, dim: str, start_date: str, end_date: str) -> int:
    """Count captures mentioning a dimension over a date range."""
    start_ts = start_date + " 00:00:00"
    end_ts = end_date + " 23:59:59"

    rows = conn.execute(
        "SELECT dimensions_json FROM captures_log "
        "WHERE created_at BETWEEN ? AND ? "
        "AND dimensions_json IS NOT NULL AND dimensions_json != '[]'",
        (start_ts, end_ts),
    ).fetchall()

    count = 0
    for row in rows:
        try:
            dims = json.loads(row[0])
            if isinstance(dims, list) and dim in dims:
                count += 1
            elif isinstance(dims, dict) and dim in dims:
                count += dims[dim] if isinstance(dims[dim], int) else 1
        except (json.JSONDecodeError, TypeError):
            continue
    return count


# ---------------------------------------------------------------------------
# Brain Level
# ---------------------------------------------------------------------------


def compute_brain_level(period: str = None, db_path=None) -> dict:
    """Compute the aggregate Brain Level for a given month.

    The Brain Level is a 1-10 score derived from five sub-scores:
    - consistency (25%): How many days had journal entries
    - breadth (25%): How many ICOR dimensions are active
    - depth (20%): Action completion ratio
    - growth (15%): Vault files created + concept promotions
    - momentum (15%): Current vs previous period engagement trend

    Args:
        period: Month in YYYY-MM format. Defaults to current month.
        db_path: Optional override for the database path.

    Returns:
        A dict matching the ``brain_level`` table columns.
    """
    if period is None:
        period = datetime.now().strftime("%Y-%m")

    year, month = int(period[:4]), int(period[5:7])
    days_in_month = calendar.monthrange(year, month)[1]
    period_start = f"{period}-01"
    period_end = f"{period}-{days_in_month:02d}"

    with get_connection(db_path=db_path) as conn:
        # --- Consistency: days with journal entries ---
        days_with_journal = conn.execute(
            "SELECT COUNT(*) FROM engagement_daily "
            "WHERE date BETWEEN ? AND ? AND journal_entry_count > 0",
            (period_start, period_end),
        ).fetchone()[0]

        # Also count journal_entries directly as fallback
        if days_with_journal == 0:
            days_with_journal = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM journal_entries "
                "WHERE date BETWEEN ? AND ?",
                (period_start, period_end),
            ).fetchone()[0]

        consistency_score = min(days_with_journal / days_in_month * 10, 10.0)

        # --- Breadth: active dimensions ---
        active_dimensions = 0
        ds_rows = conn.execute(
            "SELECT DISTINCT dimension FROM dimension_signals "
            "WHERE date BETWEEN ? AND ? AND rolling_30d_mentions > 0",
            (period_start, period_end),
        ).fetchall()
        active_dimensions = len(ds_rows)

        # Fallback: check engagement_daily dimension_mentions_json
        if active_dimensions == 0:
            dim_set = set()
            ed_rows = conn.execute(
                "SELECT dimension_mentions_json FROM engagement_daily "
                "WHERE date BETWEEN ? AND ?",
                (period_start, period_end),
            ).fetchall()
            for row in ed_rows:
                try:
                    dm = json.loads(row[0]) if row[0] else {}
                    for d, v in dm.items():
                        if isinstance(v, (int, float)) and v > 0:
                            dim_set.add(d)
                except (json.JSONDecodeError, TypeError):
                    continue
            active_dimensions = len(dim_set)

        breadth_score = (active_dimensions / 6) * 10

        # --- Depth: action completion ratio ---
        action_row = conn.execute(
            "SELECT COALESCE(SUM(actions_created), 0), "
            "COALESCE(SUM(actions_completed), 0) "
            "FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (period_start, period_end),
        ).fetchone()
        total_actions_created = action_row[0]
        total_actions_completed = action_row[1]

        depth_score = min(
            total_actions_completed / max(total_actions_created, 1) * 10, 10.0
        )

        # --- Growth: vault files + concept promotions ---
        vault_row = conn.execute(
            "SELECT COALESCE(SUM(vault_files_created), 0) "
            "FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (period_start, period_end),
        ).fetchone()
        vault_files_created = vault_row[0]

        concept_promotions = conn.execute(
            "SELECT COUNT(*) FROM concept_metadata "
            "WHERE created_at LIKE ?",
            (period + "%",),
        ).fetchone()[0]

        growth_score = min(
            (vault_files_created + concept_promotions * 3) / 20 * 10, 10.0
        )

        # --- Momentum: current vs previous period ---
        current_avg = conn.execute(
            "SELECT COALESCE(AVG(engagement_score), 0.0) "
            "FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (period_start, period_end),
        ).fetchone()[0]

        # Previous period
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        prev_days = calendar.monthrange(prev_year, prev_month)[1]
        prev_start = f"{prev_year:04d}-{prev_month:02d}-01"
        prev_end = f"{prev_year:04d}-{prev_month:02d}-{prev_days:02d}"

        previous_avg = conn.execute(
            "SELECT COALESCE(AVG(engagement_score), 0.0) "
            "FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (prev_start, prev_end),
        ).fetchone()[0]

        momentum_score = min(
            current_avg / max(previous_avg, 0.1) * 5, 10.0
        )

        # --- Days active (for metadata) ---
        days_active = conn.execute(
            "SELECT COUNT(*) FROM engagement_daily "
            "WHERE date BETWEEN ? AND ? AND engagement_score > 0",
            (period_start, period_end),
        ).fetchone()[0]

        # --- Total captures ---
        total_captures = conn.execute(
            "SELECT COALESCE(SUM(captures_count), 0) "
            "FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (period_start, period_end),
        ).fetchone()[0]

        # --- Hot / frozen dimensions ---
        hot_dims = conn.execute(
            "SELECT COUNT(DISTINCT dimension) FROM dimension_signals "
            "WHERE date BETWEEN ? AND ? AND momentum = 'hot'",
            (period_start, period_end),
        ).fetchone()[0]
        frozen_dims = conn.execute(
            "SELECT COUNT(DISTINCT dimension) FROM dimension_signals "
            "WHERE date BETWEEN ? AND ? AND momentum = 'frozen'",
            (period_start, period_end),
        ).fetchone()[0]

    # --- Composite Brain Level ---
    raw = (
        consistency_score * 0.25
        + breadth_score * 0.25
        + depth_score * 0.20
        + growth_score * 0.15
        + momentum_score * 0.15
    )
    level = max(1, min(10, round(raw)))

    result = {
        "period": period,
        "level": level,
        "consistency_score": round(consistency_score, 2),
        "breadth_score": round(breadth_score, 2),
        "depth_score": round(depth_score, 2),
        "growth_score": round(growth_score, 2),
        "momentum_score": round(momentum_score, 2),
        "days_active": days_active,
        "total_captures": total_captures,
        "total_actions_completed": total_actions_completed,
        "hot_dimensions": hot_dims,
        "frozen_dimensions": frozen_dims,
    }

    # Persist to DB
    with get_connection(db_path=db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO brain_level (
                period, level,
                consistency_score, breadth_score, depth_score,
                growth_score, momentum_score,
                days_active, total_captures, total_actions_completed,
                hot_dimensions, frozen_dimensions, computed_at
            ) VALUES (
                :period, :level,
                :consistency_score, :breadth_score, :depth_score,
                :growth_score, :momentum_score,
                :days_active, :total_captures, :total_actions_completed,
                :hot_dimensions, :frozen_dimensions, datetime('now')
            )
            """,
            result,
        )
        conn.commit()

    return result


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------


def get_latest_dimension_signals(db_path=None) -> list[dict]:
    """Return the most recent dimension signals (all 6 dimensions).

    Returns:
        A list of dicts (one per dimension) for the latest date, or an
        empty list if no signals have been computed yet.
    """
    with get_connection(db_path=db_path, row_factory=sqlite3.Row) as conn:
        latest_date_row = conn.execute(
            "SELECT MAX(date) FROM dimension_signals"
        ).fetchone()
        if not latest_date_row or latest_date_row[0] is None:
            return []

        latest_date = latest_date_row[0]
        rows = conn.execute(
            "SELECT * FROM dimension_signals WHERE date = ? "
            "ORDER BY dimension",
            (latest_date,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_current_brain_level(db_path=None) -> dict | None:
    """Return the most recent Brain Level entry.

    Returns:
        A dict matching brain_level columns, or None if no level has
        been computed yet.
    """
    with get_connection(db_path=db_path, row_factory=sqlite3.Row) as conn:
        row = conn.execute(
            "SELECT * FROM brain_level ORDER BY period DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

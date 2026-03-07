"""Pattern detection and alert management system.

Scans existing tables (action_items, captures_log, journal_entries,
engagement_daily, vault_nodes/vault_edges) for actionable patterns and
creates deduplicated alerts in the ``alerts`` table.

Schema lives in migrate-db.py (step 22d) and conftest.py.
"""

import hashlib
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
# Internal helpers
# ---------------------------------------------------------------------------


def _fingerprint(alert_type: str, dimension: str = None, key: str = "") -> str:
    """Return an MD5 hex digest that uniquely identifies a pattern instance.

    Using a fingerprint prevents duplicate alerts for the same underlying
    pattern (e.g. the same stale action being flagged on consecutive runs).
    """
    raw = f"{alert_type}:{dimension or ''}:{key}"
    return hashlib.md5(raw.encode()).hexdigest()


def _create_alert(
    alert_type: str,
    severity: str,
    title: str,
    dimension: str = None,
    details: dict = None,
    key: str = "",
    db_path=None,
) -> bool:
    """Insert a new alert if no alert with the same fingerprint already exists.

    Returns:
        True if a new alert was inserted, False if a duplicate was skipped.
    """
    fp = _fingerprint(alert_type, dimension, key)
    with get_connection(db_path=db_path) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO alerts
                (alert_type, severity, dimension, title, details_json, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert_type,
                severity,
                dimension,
                title,
                json.dumps(details or {}),
                fp,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def check_stale_actions(days_threshold: int = 7, db_path=None) -> int:
    """Flag pending action items older than *days_threshold* days.

    Returns:
        Number of new alerts created.
    """
    new_count = 0
    cutoff = (datetime.now() - timedelta(days=days_threshold)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with get_connection(db_path=db_path) as conn:
        rows = conn.execute(
            "SELECT id, description, created_at FROM action_items "
            "WHERE status = 'pending' AND created_at < ?",
            (cutoff,),
        ).fetchall()

    for row in rows:
        action_id, description, created_at = row
        try:
            created_dt = datetime.fromisoformat(created_at)
            days_stale = (datetime.now() - created_dt).days
        except (ValueError, TypeError):
            days_stale = days_threshold

        created = _create_alert(
            alert_type="stale_actions",
            severity="warning",
            title=f"Action pending for {days_stale} days: {description[:50]}",
            key=str(action_id),
            details={
                "action_id": action_id,
                "description": description,
                "days_stale": days_stale,
            },
            db_path=db_path,
        )
        if created:
            new_count += 1

    return new_count


def check_neglected_dimensions(days_threshold: int = 14, db_path=None) -> int:
    """Flag ICOR dimensions with zero activity in the last *days_threshold* days.

    Checks both ``captures_log.dimensions_json`` and
    ``journal_entries.icor_elements`` for dimension mentions.

    Returns:
        Number of new alerts created.
    """
    new_count = 0
    cutoff = (datetime.now() - timedelta(days=days_threshold)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).strftime(
        "%Y-%m-%d"
    )

    with get_connection(db_path=db_path) as conn:
        # Gather all dimension mentions from captures_log
        cap_rows = conn.execute(
            "SELECT dimensions_json FROM captures_log "
            "WHERE created_at >= ? "
            "AND dimensions_json IS NOT NULL AND dimensions_json != '[]'",
            (cutoff,),
        ).fetchall()

        active_dims = set()
        for cap_row in cap_rows:
            try:
                dims = json.loads(cap_row[0])
                if isinstance(dims, list):
                    for d in dims:
                        if isinstance(d, str):
                            active_dims.add(d)
                elif isinstance(dims, dict):
                    for d in dims:
                        active_dims.add(d)
            except (json.JSONDecodeError, TypeError):
                continue

        # Also check journal_entries icor_elements
        je_rows = conn.execute(
            "SELECT icor_elements FROM journal_entries "
            "WHERE date >= ?",
            (cutoff_date,),
        ).fetchall()

        for je_row in je_rows:
            try:
                elems = json.loads(je_row[0] or "[]")
                if isinstance(elems, list):
                    for e in elems:
                        if isinstance(e, str):
                            active_dims.add(e)
            except (json.JSONDecodeError, TypeError):
                continue

    for dimension in _ICOR_DIMENSIONS:
        if dimension not in active_dims:
            severity = "warning" if days_threshold > 21 else "info"
            created = _create_alert(
                alert_type="neglected_dimension",
                severity=severity,
                title=f"{dimension} has had no activity for {days_threshold}+ days",
                dimension=dimension,
                key=dimension,
                db_path=db_path,
            )
            if created:
                new_count += 1

    return new_count


def check_engagement_drop(threshold: float = 0.5, db_path=None) -> int:
    """Flag when average engagement dropped by *threshold* or more vs prior week.

    Compares the average ``engagement_score`` for the last 7 days against
    the previous 7 days.

    Returns:
        Number of new alerts created.
    """
    new_count = 0
    today = datetime.now().date()
    current_start = (today - timedelta(days=6)).isoformat()
    current_end = today.isoformat()
    previous_start = (today - timedelta(days=13)).isoformat()
    previous_end = (today - timedelta(days=7)).isoformat()

    with get_connection(db_path=db_path) as conn:
        row = conn.execute(
            "SELECT AVG(engagement_score) FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (current_start, current_end),
        ).fetchone()
        current_avg = row[0] if row and row[0] is not None else None

        row = conn.execute(
            "SELECT AVG(engagement_score) FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (previous_start, previous_end),
        ).fetchone()
        previous_avg = row[0] if row and row[0] is not None else None

    if current_avg is None or previous_avg is None or previous_avg == 0:
        return 0

    if current_avg < previous_avg * threshold:
        drop_pct = ((previous_avg - current_avg) / previous_avg) * 100
        severity = "critical" if current_avg < 2 else "warning"
        week_number = datetime.now().isocalendar()[1]
        created = _create_alert(
            alert_type="engagement_drop",
            severity=severity,
            title=f"Engagement dropped {drop_pct:.0f}% vs previous week",
            details={
                "current_avg": round(current_avg, 2),
                "previous_avg": round(previous_avg, 2),
            },
            key=f"week-{week_number}",
            db_path=db_path,
        )
        if created:
            new_count += 1

    return new_count


def check_streak_break(db_path=None) -> int:
    """Flag if a journaling streak was broken (no entry yesterday but 3+ days before).

    Returns:
        Number of new alerts created.
    """
    new_count = 0
    today = datetime.now().date()
    yesterday = (today - timedelta(days=1)).isoformat()

    with get_connection(db_path=db_path) as conn:
        # Check if yesterday has a journal entry
        yesterday_count = conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE date = ?",
            (yesterday,),
        ).fetchone()[0]

        if yesterday_count > 0:
            return 0

        # Check if there was a streak (3 consecutive days before yesterday)
        streak_days = 0
        for offset in range(2, 32):  # Check up to 30 days back
            check_date = (today - timedelta(days=offset)).isoformat()
            has_entry = conn.execute(
                "SELECT COUNT(*) FROM journal_entries WHERE date = ?",
                (check_date,),
            ).fetchone()[0]
            if has_entry > 0:
                streak_days += 1
            else:
                break

    if streak_days >= 3:
        created = _create_alert(
            alert_type="streak_break",
            severity="info",
            title="Journal streak broken - no entry yesterday",
            details={"streak_days": streak_days},
            key=f"streak-{yesterday}",
            db_path=db_path,
        )
        if created:
            new_count += 1

    return new_count


def check_drift_alerts(db_path=None) -> int:
    """Flag dimensions where mentions dropped 60%+ vs prior 14 days.

    Compares ``dimension_mentions_json`` across ``engagement_daily`` rows
    for the last 14 days against the previous 14 days.

    Returns:
        Number of new alerts created.
    """
    new_count = 0
    today = datetime.now().date()
    current_start = (today - timedelta(days=13)).isoformat()
    current_end = today.isoformat()
    previous_start = (today - timedelta(days=27)).isoformat()
    previous_end = (today - timedelta(days=14)).isoformat()

    def _sum_mentions(conn, start, end):
        """Aggregate dimension mentions across a date range."""
        totals = {d: 0 for d in _ICOR_DIMENSIONS}
        rows = conn.execute(
            "SELECT dimension_mentions_json FROM engagement_daily "
            "WHERE date BETWEEN ? AND ?",
            (start, end),
        ).fetchall()
        for row in rows:
            try:
                mentions = json.loads(row[0] or "{}")
                for dim, count in mentions.items():
                    if dim in totals and isinstance(count, (int, float)):
                        totals[dim] += count
            except (json.JSONDecodeError, TypeError):
                continue
        return totals

    with get_connection(db_path=db_path) as conn:
        current_mentions = _sum_mentions(conn, current_start, current_end)
        previous_mentions = _sum_mentions(conn, previous_start, previous_end)

    week_number = datetime.now().isocalendar()[1]

    for dimension in _ICOR_DIMENSIONS:
        prev = previous_mentions.get(dimension, 0)
        curr = current_mentions.get(dimension, 0)
        if prev <= 0:
            continue
        drop_pct = ((prev - curr) / prev) * 100
        if drop_pct >= 60:
            created = _create_alert(
                alert_type="drift",
                severity="warning",
                title=f"Drift detected: {dimension} activity down {drop_pct:.0f}%",
                dimension=dimension,
                details={
                    "current_mentions": curr,
                    "previous_mentions": prev,
                },
                key=f"drift-{dimension}-week-{week_number}",
                db_path=db_path,
            )
            if created:
                new_count += 1

    return new_count


def check_knowledge_gaps(min_edges: int = 2, db_path=None) -> int:
    """Flag vault documents with fewer than *min_edges* outgoing edges.

    Returns:
        Number of new alerts created (capped at 5 most recent).
    """
    new_count = 0
    with get_connection(db_path=db_path) as conn:
        rows = conn.execute(
            """
            SELECT n.file_path, n.title,
                   COUNT(e.id) AS edge_count
            FROM vault_nodes n
            LEFT JOIN vault_edges e ON n.id = e.source_node_id
            WHERE n.node_type = 'document'
            GROUP BY n.id
            HAVING edge_count < ?
            ORDER BY n.indexed_at DESC
            LIMIT 5
            """,
            (min_edges,),
        ).fetchall()

    for row in rows:
        file_path, title, edge_count = row
        created = _create_alert(
            alert_type="knowledge_gap",
            severity="info",
            title=f"Isolated note: {title} has {edge_count} connections",
            details={"file_path": file_path, "edge_count": edge_count},
            key=file_path,
            db_path=db_path,
        )
        if created:
            new_count += 1

    return new_count


def run_all_checks(db_path=None) -> dict:
    """Execute all detection checks and return a summary.

    Returns:
        ``{"total_new": int, "by_type": {alert_type: count, ...}}``
    """
    results = {
        "stale_actions": check_stale_actions(db_path=db_path),
        "neglected_dimension": check_neglected_dimensions(db_path=db_path),
        "engagement_drop": check_engagement_drop(db_path=db_path),
        "streak_break": check_streak_break(db_path=db_path),
        "drift": check_drift_alerts(db_path=db_path),
        "knowledge_gap": check_knowledge_gaps(db_path=db_path),
    }
    return {
        "total_new": sum(results.values()),
        "by_type": results,
    }


# ---------------------------------------------------------------------------
# Management functions
# ---------------------------------------------------------------------------


def dismiss_alert(alert_id: int, db_path=None) -> bool:
    """Mark an active alert as dismissed.

    Returns:
        True if the alert was updated, False if not found or already dismissed.
    """
    with get_connection(db_path=db_path) as conn:
        cursor = conn.execute(
            "UPDATE alerts SET status = 'dismissed', dismissed_at = datetime('now') "
            "WHERE id = ? AND status = 'active'",
            (alert_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_active_alerts(limit: int = 10, db_path=None) -> list[dict]:
    """Return active alerts ordered by severity (critical first), then recency.

    Returns:
        A list of dicts with all alert columns.
    """
    with get_connection(db_path=db_path, row_factory=sqlite3.Row) as conn:
        rows = conn.execute(
            """
            SELECT * FROM alerts
            WHERE status = 'active'
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'warning' THEN 1
                    WHEN 'info' THEN 2
                END,
                created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

"""Pre-computed analytics for ICOR drift, stale items, clusters, and morning briefing."""
import json
import logging
from collections import defaultdict
from pathlib import Path

from core.db_ops import query

logger = logging.getLogger(__name__)


async def compute_drift_scores(days: int = 60, db_path: Path = None) -> list[dict]:
    """Compare stated ICOR priorities vs actual journal mention frequency.

    Returns list of dicts sorted by deviation (highest gap first):
    [{element, dimension, attention_score, mentions_30d, deviation, drift_status}]
    """
    rows = await query(
        "WITH element_mentions AS ("
        "  SELECT json_each.value AS element_name, COUNT(*) AS mention_count "
        "  FROM journal_entries, json_each(journal_entries.icor_elements) "
        "  WHERE journal_entries.date >= date('now', ?) "
        "  GROUP BY json_each.value"
        ") "
        "SELECT h.name AS element, p.name AS dimension, "
        "  h.attention_score, COALESCE(em.mention_count, 0) AS mentions_30d "
        "FROM icor_hierarchy h "
        "JOIN icor_hierarchy p ON h.parent_id = p.id "
        "LEFT JOIN element_mentions em ON em.element_name = h.name "
        "WHERE h.level = 'key_element'",
        (f"-{days} days",),
        db_path=db_path,
    )

    if not rows:
        return []

    max_attention = max((r.get("attention_score", 0) or 0 for r in rows), default=1) or 1
    max_mentions = max((r.get("mentions_30d", 0) for r in rows), default=1) or 1

    results = []
    for r in rows:
        stated = (r.get("attention_score", 0) or 0) / max_attention
        actual = r["mentions_30d"] / max_mentions
        deviation = round(abs(stated - actual), 2)

        if deviation > 0.6:
            status = "high_gap"
        elif deviation > 0.3:
            status = "moderate_gap"
        else:
            status = "aligned"

        results.append({
            "element": r["element"],
            "dimension": r["dimension"],
            "attention_score": r.get("attention_score", 0),
            "mentions_30d": r["mentions_30d"],
            "deviation": deviation,
            "drift_status": status,
        })

    results.sort(key=lambda x: x["deviation"], reverse=True)
    return results


async def detect_stale_actions(stale_days: int = 14, db_path: Path = None) -> list[dict]:
    """Find pending actions older than stale_days, grouped by element.

    Returns list of dicts sorted by oldest action:
    [{element, action_count, oldest_age_days, actions: [{description, source_date, age_days}]}]
    """
    actions = await query(
        "SELECT id, description, icor_element, source_date, "
        "CAST(julianday('now') - julianday(source_date) AS INTEGER) AS age_days "
        "FROM action_items "
        "WHERE status = 'pending' "
        "AND source_date <= date('now', ?) "
        "ORDER BY source_date ASC",
        (f"-{stale_days} days",),
        db_path=db_path,
    )

    if not actions:
        return []

    groups = defaultdict(list)
    for a in actions:
        elem = a.get("icor_element") or "Unassigned"
        groups[elem].append({
            "description": a["description"],
            "source_date": a["source_date"],
            "age_days": a["age_days"],
        })

    results = []
    for elem, elem_actions in groups.items():
        oldest = max(a["age_days"] for a in elem_actions)
        results.append({
            "element": elem,
            "action_count": len(elem_actions),
            "oldest_age_days": oldest,
            "actions": elem_actions,
        })

    results.sort(key=lambda x: x["oldest_age_days"], reverse=True)
    return results


async def find_co_occurrence_clusters(min_co: int = 3, db_path: Path = None) -> list[dict]:
    """Find ICOR elements that frequently appear together in journal entries.

    Returns list of co-occurring pairs:
    [{elem1, elem2, co_count}]
    """
    entries = await query(
        "SELECT date, icor_elements FROM journal_entries "
        "WHERE json_array_length(icor_elements) > 1 "
        "AND date >= date('now', '-60 days')",
        db_path=db_path,
    )

    if not entries:
        return []

    pair_counts = defaultdict(int)
    for entry in entries:
        try:
            elements = json.loads(entry.get("icor_elements", "[]"))
        except (json.JSONDecodeError, TypeError):
            continue
        elements = sorted(set(elements))
        for i in range(len(elements)):
            for j in range(i + 1, len(elements)):
                pair_counts[(elements[i], elements[j])] += 1

    results = []
    for (e1, e2), count in pair_counts.items():
        if count >= min_co:
            results.append({
                "elem1": e1,
                "elem2": e2,
                "co_count": count,
            })

    results.sort(key=lambda x: x["co_count"], reverse=True)
    return results


async def compute_attention_gaps(db_path: Path = None) -> list[dict]:
    """Find ICOR elements with attention below their dimension average.

    Returns list of elements with gaps:
    [{element, dimension, attention_score, mentions_30d, gap_severity}]
    """
    rows = await query(
        "WITH element_mentions AS ("
        "  SELECT json_each.value AS element_name, COUNT(*) AS mention_count "
        "  FROM journal_entries, json_each(journal_entries.icor_elements) "
        "  WHERE journal_entries.date >= date('now', '-30 days') "
        "  GROUP BY json_each.value"
        "), "
        "dim_avgs AS ("
        "  SELECT p.id AS dim_id, AVG(h.attention_score) AS avg_score "
        "  FROM icor_hierarchy h "
        "  JOIN icor_hierarchy p ON h.parent_id = p.id "
        "  WHERE h.level = 'key_element' "
        "  GROUP BY p.id"
        ") "
        "SELECT h.name AS element, p.name AS dimension, "
        "  h.attention_score, COALESCE(em.mention_count, 0) AS mentions_30d, "
        "  da.avg_score AS dim_avg "
        "FROM icor_hierarchy h "
        "JOIN icor_hierarchy p ON h.parent_id = p.id "
        "LEFT JOIN element_mentions em ON em.element_name = h.name "
        "LEFT JOIN dim_avgs da ON p.id = da.dim_id "
        "WHERE h.level = 'key_element'",
        db_path=db_path,
    )

    results = []
    for r in rows:
        score = r.get("attention_score", 0) or 0
        avg = r.get("dim_avg", 0) or 0
        mentions = r.get("mentions_30d", 0)

        if score == 0 and mentions == 0:
            severity = "critical"
        elif avg > 0 and score < avg * 0.5:
            severity = "high"
        elif avg > 0 and score < avg:
            severity = "moderate"
        else:
            severity = "aligned"

        if severity != "aligned":
            results.append({
                "element": r["element"],
                "dimension": r["dimension"],
                "attention_score": score,
                "mentions_30d": mentions,
                "gap_severity": severity,
            })

    severity_order = {"critical": 0, "high": 1, "moderate": 2}
    results.sort(key=lambda x: severity_order.get(x["gap_severity"], 3))
    return results


async def compute_top3_morning(db_path: Path = None) -> list[dict]:
    """Top 3 priority actions for morning briefing.

    Composite score: age_days * 0.6 + project_bonus(10 if has project).
    Returns top 3 sorted by composite score desc.
    """
    rows = await query(
        "SELECT id, description, icor_element, icor_project, source_date, "
        "CAST(julianday('now') - julianday(source_date) AS INTEGER) AS age_days "
        "FROM action_items "
        "WHERE status = 'pending' "
        "ORDER BY source_date ASC",
        db_path=db_path,
    )

    if not rows:
        return []

    for r in rows:
        age = r.get("age_days", 0) or 0
        project_bonus = 10 if r.get("icor_project") else 0
        r["composite_score"] = age * 0.6 + project_bonus

    rows.sort(key=lambda x: x["composite_score"], reverse=True)
    return rows[:3]


async def compute_stuck_item(stale_days: int = 14, db_path: Path = None) -> dict | None:
    """Find the single longest-pending action item (the 'stuck' item).

    Returns dict with description, age_days, element or None.
    """
    rows = await query(
        "SELECT description, icor_element, source_date, "
        "CAST(julianday('now') - julianday(source_date) AS INTEGER) AS age_days "
        "FROM action_items "
        "WHERE status = 'pending' "
        "ORDER BY source_date ASC LIMIT 1",
        db_path=db_path,
    )

    if rows and rows[0].get("age_days", 0) >= stale_days:
        return rows[0]
    return None

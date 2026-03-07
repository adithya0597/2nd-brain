"""Async SQLite operations for Second Brain database."""
import logging
from pathlib import Path

import aiosqlite

import config
from core.db_connection import get_async_connection

logger = logging.getLogger(__name__)


async def query(sql: str, params: tuple = (), db_path: Path = None) -> list[dict]:
    """Run a SELECT query and return results as a list of dicts."""
    async with get_async_connection(db_path, row_factory=aiosqlite.Row) as db:
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def execute(sql: str, params: tuple = (), db_path: Path = None) -> int:
    """Run an INSERT/UPDATE/DELETE and return lastrowid."""
    async with get_async_connection(db_path) as db:
        cursor = await db.execute(sql, params)
        await db.commit()
        return cursor.lastrowid


async def get_pending_actions(db_path: Path = None) -> list[dict]:
    """Return all pending action items."""
    return await query(
        "SELECT id, description, source_file, source_date, icor_element, icor_project "
        "FROM action_items WHERE status = 'pending' ORDER BY created_at DESC",
        db_path=db_path,
    )


async def get_icor_hierarchy(db_path: Path = None) -> list[dict]:
    """Return the full ICOR hierarchy tree."""
    return await query(
        "SELECT h.id, h.level, h.name, p.name AS parent_name, "
        "h.attention_score, h.last_mentioned, h.notion_page_id "
        "FROM icor_hierarchy h "
        "LEFT JOIN icor_hierarchy p ON h.parent_id = p.id "
        "ORDER BY h.id",
        db_path=db_path,
    )


async def get_attention_scores(db_path: Path = None) -> list[dict]:
    """Return current attention scores (latest period) with dimension names."""
    return await query(
        "SELECT ai.icor_element_id, h.name, p.name AS dimension, ai.mention_count, "
        "ai.journal_days, ai.attention_score, ai.flagged "
        "FROM attention_indicators ai "
        "JOIN icor_hierarchy h ON ai.icor_element_id = h.id "
        "LEFT JOIN icor_hierarchy p ON h.parent_id = p.id "
        "WHERE ai.period_end = (SELECT MAX(period_end) FROM attention_indicators) "
        "ORDER BY ai.attention_score DESC",
        db_path=db_path,
    )


async def get_recent_journal(days: int = 7, db_path: Path = None) -> list[dict]:
    """Return journal entries from the last N days."""
    return await query(
        "SELECT date, content, mood, energy, icor_elements, summary, sentiment_score "
        "FROM journal_entries WHERE date >= date('now', ?) ORDER BY date DESC",
        (f"-{days} days",),
        db_path=db_path,
    )


async def insert_action_item(
    description: str,
    source: str,
    icor_element: str = None,
    icor_project: str = None,
    db_path: Path = None,
) -> int:
    """Insert a new pending action item. Returns the new row ID."""
    return await execute(
        "INSERT INTO action_items (description, source_file, source_date, icor_element, icor_project, status, created_at) "
        "VALUES (?, ?, date('now'), ?, ?, 'pending', datetime('now'))",
        (description, source, icor_element, icor_project),
        db_path=db_path,
    )


async def get_neglected_elements(days: int = 7, db_path: Path = None) -> list[dict]:
    """Return ICOR key elements not mentioned in the last N days."""
    return await query(
        "SELECT h.id, h.name, p.name AS dimension, h.last_mentioned, "
        "julianday('now') - julianday(h.last_mentioned) AS days_since "
        "FROM icor_hierarchy h "
        "JOIN icor_hierarchy p ON h.parent_id = p.id "
        "WHERE h.level = 'key_element' "
        "AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', ?)) "
        "ORDER BY h.last_mentioned ASC NULLS FIRST",
        (f"-{days} days",),
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Sync-related queries
# ---------------------------------------------------------------------------


async def get_sync_state(entity_type: str, db_path: Path = None) -> dict | None:
    """Get the sync state for an entity type."""
    rows = await query(
        "SELECT entity_type, last_synced_at, items_synced, last_sync_direction, updated_at "
        "FROM sync_state WHERE entity_type = ?",
        (entity_type,),
        db_path=db_path,
    )
    return rows[0] if rows else None


async def update_sync_state(
    entity_type: str,
    last_synced_at: str,
    items_synced: int,
    direction: str = "push",
    db_path: Path = None,
) -> int:
    """Update sync state after a sync operation."""
    return await execute(
        "UPDATE sync_state SET last_synced_at = ?, items_synced = ?, "
        "last_sync_direction = ?, updated_at = datetime('now') "
        "WHERE entity_type = ?",
        (last_synced_at, items_synced, direction, entity_type),
        db_path=db_path,
    )


async def get_unpushed_actions(db_path: Path = None) -> list[dict]:
    """Get action items that haven't been pushed to Notion yet.

    TTL hack removed — sync_outbox handles idempotency now.
    """
    return await query(
        "SELECT id, description, source_file, source_date, icor_element, icor_project, status "
        "FROM action_items WHERE status = 'pending' AND external_id IS NULL "
        "ORDER BY created_at ASC",
        db_path=db_path,
    )


async def get_pushed_actions(db_path: Path = None) -> list[dict]:
    """Get action items that have been pushed to Notion (have external_id)."""
    return await query(
        "SELECT id, description, status, external_id, external_system "
        "FROM action_items WHERE external_id IS NOT NULL AND external_system = 'notion_tasks' "
        "ORDER BY created_at DESC",
        db_path=db_path,
    )


async def update_action_external(
    action_id: int, external_id: str, db_path: Path = None
) -> int:
    """Set the Notion page ID on an action item after pushing it."""
    return await execute(
        "UPDATE action_items SET external_id = ?, external_system = 'notion_tasks' "
        "WHERE id = ?",
        (external_id, action_id),
        db_path=db_path,
    )


async def update_action_status_from_notion(
    action_id: int, status: str, db_path: Path = None
) -> int:
    """Update a local action item's status based on Notion task status."""
    return await execute(
        "UPDATE action_items SET status = ? WHERE id = ?",
        (status, action_id),
        db_path=db_path,
    )


async def get_unsynced_journal_entries(db_path: Path = None) -> list[dict]:
    """Get journal entries not yet synced to Notion."""
    return await query(
        "SELECT date, content, mood, energy, icor_elements, summary, sentiment_score "
        "FROM journal_entries "
        "WHERE date NOT IN (SELECT source_file FROM vault_sync_log WHERE target = 'notion_notes' AND status = 'success') "
        "ORDER BY date ASC",
        db_path=db_path,
    )


async def get_unsynced_concepts(db_path: Path = None) -> list[dict]:
    """Get concepts (growing/evergreen) not yet pushed to Notion."""
    return await query(
        "SELECT id, title AS name, file_path, status, mention_count, last_mentioned, icor_elements "
        "FROM concept_metadata WHERE notion_id IS NULL "
        "AND status IN ('growing', 'evergreen') "
        "ORDER BY mention_count DESC",
        db_path=db_path,
    )


async def update_concept_notion_id(
    concept_id: int, notion_id: str, db_path: Path = None
) -> int:
    """Set the Notion page ID on a concept after pushing it."""
    return await execute(
        "UPDATE concept_metadata SET notion_id = ? WHERE id = ?",
        (notion_id, concept_id),
        db_path=db_path,
    )


async def update_icor_notion_page_id(
    icor_id: int, notion_page_id: str, db_path: Path = None
) -> int:
    """Set the Notion page ID on an ICOR hierarchy element."""
    return await execute(
        "UPDATE icor_hierarchy SET notion_page_id = ? WHERE id = ?",
        (notion_page_id, icor_id),
        db_path=db_path,
    )


async def log_sync_operation(
    operation: str,
    source_file: str,
    target: str,
    status: str,
    details: str = "",
    db_path: Path = None,
) -> int:
    """Insert a record into vault_sync_log."""
    return await execute(
        "INSERT INTO vault_sync_log (operation, source_file, target, status, details, created_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (operation, source_file, target, status, details),
        db_path=db_path,
    )


async def get_cost_summary(days: int = 30, db_path: Path = None) -> dict:
    """Get API cost summary grouped by day and caller."""
    daily = await query(
        """SELECT DATE(created_at) AS date,
                  COUNT(*) AS calls,
                  SUM(cost_estimate_usd) AS daily_cost,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens
           FROM api_token_logs
           WHERE created_at >= datetime('now', ?)
           GROUP BY DATE(created_at)
           ORDER BY date DESC""",
        (f"-{days} days",),
        db_path=db_path,
    )
    by_caller = await query(
        """SELECT caller,
                  COUNT(*) AS calls,
                  SUM(cost_estimate_usd) AS total_cost,
                  AVG(input_tokens) AS avg_input,
                  AVG(output_tokens) AS avg_output
           FROM api_token_logs
           WHERE created_at >= datetime('now', ?)
           GROUP BY caller
           ORDER BY total_cost DESC""",
        (f"-{days} days",),
        db_path=db_path,
    )
    by_model = await query(
        """SELECT model,
                  COUNT(*) AS calls,
                  SUM(cost_estimate_usd) AS total_cost
           FROM api_token_logs
           WHERE created_at >= datetime('now', ?)
           GROUP BY model
           ORDER BY total_cost DESC""",
        (f"-{days} days",),
        db_path=db_path,
    )
    return {"daily": daily, "by_caller": by_caller, "by_model": by_model}


async def insert_concept_metadata(
    title: str,
    file_path: str,
    icor_elements: list[str],
    first_mentioned: str,
    last_mentioned: str = "",
    mention_count: int = 1,
    summary: str = "",
    status: str = "seedling",
    db_path: Path = None,
) -> int:
    """Insert a new concept into concept_metadata. Returns the new row ID."""
    import json as _json
    elements_json = _json.dumps(icor_elements)
    return await execute(
        "INSERT OR IGNORE INTO concept_metadata "
        "(title, file_path, status, icor_elements, first_mentioned, last_mentioned, "
        "mention_count, summary, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (title, file_path, status, elements_json, first_mentioned,
         last_mentioned or first_mentioned, mention_count, summary),
        db_path=db_path,
    )


async def compute_attention_scores(days: int = 30, db_path: Path = None) -> int:
    """Compute attention scores from journal entries and populate attention_indicators.

    Scans journal_entries for the last N days, counts mentions per ICOR key element,
    and inserts/replaces rows in attention_indicators. Also updates last_mentioned
    on icor_hierarchy.

    Returns the number of elements scored.
    """
    import json as _json
    from datetime import date, timedelta

    db_path = db_path or config.DB_PATH
    today = date.today().isoformat()
    period_start = (date.today() - timedelta(days=days)).isoformat()

    async with get_async_connection(db_path, row_factory=aiosqlite.Row) as db:
        # 1. Get all key elements
        async with db.execute(
            "SELECT id, name FROM icor_hierarchy WHERE level = 'key_element'"
        ) as cursor:
            elements = [dict(r) for r in await cursor.fetchall()]

        if not elements:
            return 0

        # 2. Get journal entries for the period
        async with db.execute(
            "SELECT date, icor_elements FROM journal_entries WHERE date >= ?",
            (period_start,),
        ) as cursor:
            entries = [dict(r) for r in await cursor.fetchall()]

        # 3. Count mentions per element
        mention_counts: dict[str, int] = {}
        journal_days: dict[str, set] = {}
        last_mentioned: dict[str, str] = {}

        for entry in entries:
            try:
                icor_els = _json.loads(entry.get("data") or entry.get("icor_elements") or "[]")
            except (ValueError, TypeError):
                icor_els = []

            entry_date = entry.get("date", "")
            for el_name in icor_els:
                mention_counts[el_name] = mention_counts.get(el_name, 0) + 1
                if el_name not in journal_days:
                    journal_days[el_name] = set()
                journal_days[el_name].add(entry_date)
                if entry_date > last_mentioned.get(el_name, ""):
                    last_mentioned[el_name] = entry_date

        # 4. Compute scores and insert
        total_days = max(len(entries), 1)
        scored = 0

        for el in elements:
            name = el["name"]
            el_id = el["id"]
            mentions = mention_counts.get(name, 0)
            days_active = len(journal_days.get(name, set()))

            # Score: normalized 0-10 based on mention frequency and consistency
            frequency_score = min(mentions / total_days, 1.0) * 5
            consistency_score = min(days_active / total_days, 1.0) * 5
            score = round(frequency_score + consistency_score, 2)
            flagged = 1 if mentions == 0 else 0

            # Delete existing row for this element+period, then insert
            await db.execute(
                "DELETE FROM attention_indicators "
                "WHERE icor_element_id = ? AND period_start = ? AND period_end = ?",
                (el_id, period_start, today),
            )
            await db.execute(
                "INSERT INTO attention_indicators "
                "(icor_element_id, period_start, period_end, mention_count, "
                "journal_days, attention_score, flagged) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (el_id, period_start, today, mentions, days_active, score, flagged),
            )

            # Update last_mentioned on icor_hierarchy
            if name in last_mentioned:
                await db.execute(
                    "UPDATE icor_hierarchy SET last_mentioned = ? WHERE id = ? "
                    "AND (last_mentioned IS NULL OR last_mentioned < ?)",
                    (last_mentioned[name], el_id, last_mentioned[name]),
                )

            scored += 1

        await db.commit()
        return scored


async def get_icor_without_notion_id(db_path: Path = None) -> list[dict]:
    """Get ICOR hierarchy entries that don't have a Notion page ID."""
    return await query(
        "SELECT id, level, name, parent_id "
        "FROM icor_hierarchy WHERE notion_page_id IS NULL "
        "ORDER BY id ASC",
        db_path=db_path,
    )

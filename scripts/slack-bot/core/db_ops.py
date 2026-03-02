"""Async SQLite operations for Second Brain database."""
import logging
from pathlib import Path

import aiosqlite

from .. import config

logger = logging.getLogger(__name__)


async def query(sql: str, params: tuple = (), db_path: Path = None) -> list[dict]:
    """Run a SELECT query and return results as a list of dicts."""
    db_path = db_path or config.DB_PATH
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def execute(sql: str, params: tuple = (), db_path: Path = None) -> int:
    """Run an INSERT/UPDATE/DELETE and return lastrowid."""
    db_path = db_path or config.DB_PATH
    async with aiosqlite.connect(str(db_path)) as db:
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
    """Return current attention scores (latest period)."""
    return await query(
        "SELECT ai.icor_element_id, h.name, ai.mention_count, "
        "ai.journal_days, ai.attention_score, ai.flagged "
        "FROM attention_indicators ai "
        "JOIN icor_hierarchy h ON ai.icor_element_id = h.id "
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

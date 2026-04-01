"""Transactional outbox for Notion sync operations.

Provides idempotent enqueue, batch dequeue, confirm/fail lifecycle, and
stale-processing sweep. All functions are async, matching the notion_sync.py
execution context.

Schema lives in migrate-db.py (step 21) and conftest.py.
"""

import logging
from pathlib import Path

import aiosqlite

from core.db_connection import get_async_connection

logger = logging.getLogger(__name__)


async def enqueue(
    entity_type: str,
    entity_id: str,
    operation: str,
    payload_json: str,
    db_path: Path = None,
) -> int | None:
    """Insert a pending outbox row. Returns the row ID, or None if deduplicated.

    UNIQUE(entity_type, entity_id, operation) prevents duplicates:
    - If an existing row has status='pending' or 'processing', skip (return None).
    - If an existing row has status='confirmed', create a new row with 'update' operation.
    - If an existing row has status='failed' or 'dead_letter', reset it to pending.
    """
    async with get_async_connection(db_path, row_factory=aiosqlite.Row) as db:
        # Check for existing row with same key
        async with db.execute(
            "SELECT id, status FROM sync_outbox "
            "WHERE entity_type = ? AND entity_id = ? AND operation = ?",
            (entity_type, entity_id, operation),
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            status = existing["status"]
            if status in ("pending", "processing"):
                # Already queued, skip
                return None
            if status == "confirmed" and operation == "create":
                # Already pushed; enqueue as 'update' instead
                return await enqueue(
                    entity_type, entity_id, "update", payload_json, db_path
                )
            if status in ("failed", "dead_letter"):
                # Reset for retry with fresh payload
                cursor = await db.execute(
                    "UPDATE sync_outbox SET status = 'pending', payload_json = ?, "
                    "attempt_count = 0, error_message = NULL, processing_at = NULL "
                    "WHERE id = ?",
                    (payload_json, existing["id"]),
                )
                await db.commit()
                return existing["id"]

        # No existing row (or confirmed + already 'update') — insert
        try:
            cursor = await db.execute(
                "INSERT INTO sync_outbox (entity_type, entity_id, operation, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (entity_type, entity_id, operation, payload_json),
            )
            await db.commit()
            return cursor.lastrowid
        except Exception:
            # UNIQUE constraint violation from race — treat as dedup
            await db.rollback()
            return None


async def dequeue_batch(
    limit: int = 50,
    db_path: Path = None,
) -> list[dict]:
    """Atomically select pending rows and mark them 'processing'.

    Returns a list of dicts with all outbox columns.
    """
    async with get_async_connection(db_path, row_factory=aiosqlite.Row) as db:
        # Select pending rows
        async with db.execute(
            "SELECT id, entity_type, entity_id, operation, payload_json, "
            "attempt_count, max_attempts "
            "FROM sync_outbox WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]

        if not rows:
            return []

        # Mark them processing
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        await db.execute(
            f"UPDATE sync_outbox SET status = 'processing', "
            f"processing_at = datetime('now') WHERE id IN ({placeholders})",
            ids,
        )
        await db.commit()
        return rows


async def confirm(
    outbox_id: int,
    notion_page_id: str,
    db_path: Path = None,
) -> None:
    """Mark an outbox row as confirmed with the resulting Notion page ID."""
    async with get_async_connection(db_path) as db:
        await db.execute(
            "UPDATE sync_outbox SET status = 'confirmed', notion_page_id = ?, "
            "confirmed_at = datetime('now') WHERE id = ?",
            (notion_page_id, outbox_id),
        )
        await db.commit()


async def fail(
    outbox_id: int,
    error_message: str,
    db_path: Path = None,
) -> None:
    """Record a failure. Retries under max_attempts, dead-letters at the limit."""
    async with get_async_connection(db_path, row_factory=aiosqlite.Row) as db:
        async with db.execute(
            "SELECT attempt_count, max_attempts FROM sync_outbox WHERE id = ?",
            (outbox_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            logger.warning("Outbox row %d not found for fail()", outbox_id)
            return

        new_count = row["attempt_count"] + 1
        if new_count >= row["max_attempts"]:
            new_status = "dead_letter"
        else:
            new_status = "pending"  # back to pending for retry

        await db.execute(
            "UPDATE sync_outbox SET status = ?, attempt_count = ?, "
            "error_message = ?, processing_at = NULL WHERE id = ?",
            (new_status, new_count, error_message, outbox_id),
        )
        await db.commit()


async def sweep_stale(
    timeout_minutes: int = 10,
    db_path: Path = None,
) -> int:
    """Reset rows stuck in 'processing' beyond the timeout back to 'pending'.

    Returns the number of rows swept.
    """
    async with get_async_connection(db_path) as db:
        cursor = await db.execute(
            "UPDATE sync_outbox SET status = 'pending', processing_at = NULL "
            "WHERE status = 'processing' "
            "AND processing_at < datetime('now', ?)",
            (f"-{timeout_minutes} minutes",),
        )
        await db.commit()
        return cursor.rowcount

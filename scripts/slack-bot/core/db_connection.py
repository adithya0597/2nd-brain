"""Centralized SQLite connection factory.

All database access should go through this module to ensure consistent
PRAGMA configuration, WAL mode, foreign key enforcement, and connection
lifecycle management.

Rationale: Before this module, 6+ files independently created connections
with inconsistent PRAGMA setup. token_logger and fts_index never set WAL
or FK enforcement at all. This module fixes that.
"""

import logging
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import aiosqlite

import config

logger = logging.getLogger(__name__)

# Applied to every connection — sync and async.
# Order matters: journal_mode must come first (changes file layout).
_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-8000",       # ~8MB cache
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",    # 256MB memory-mapped I/O
]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply all PRAGMAs to a sync connection."""
    for pragma in _PRAGMAS:
        conn.execute(pragma)


async def _apply_pragmas_async(db: aiosqlite.Connection) -> None:
    """Apply all PRAGMAs to an async connection."""
    for pragma in _PRAGMAS:
        await db.execute(pragma)


@contextmanager
def get_connection(db_path: Path = None, row_factory=None):
    """Context manager returning a configured sync SQLite connection.

    Usage::

        with get_connection() as conn:
            conn.execute("SELECT ...")

    The connection is automatically closed on exit. If an exception occurs
    inside the block, any uncommitted transaction is rolled back.
    """
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(str(db_path))
    _apply_pragmas(conn)
    if row_factory:
        conn.row_factory = row_factory
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@asynccontextmanager
async def get_async_connection(db_path: Path = None, row_factory=None):
    """Context manager returning a configured async aiosqlite connection.

    Usage::

        async with get_async_connection() as db:
            await db.execute("SELECT ...")

    """
    db_path = db_path or config.DB_PATH
    async with aiosqlite.connect(str(db_path)) as db:
        await _apply_pragmas_async(db)
        if row_factory:
            db.row_factory = row_factory
        yield db

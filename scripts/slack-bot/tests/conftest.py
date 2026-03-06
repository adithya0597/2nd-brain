"""Shared fixtures for Second Brain Slack bot tests."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: add the slack-bot directory to sys.path so we can import config,
# core.*, etc. as the bot itself does.
# ---------------------------------------------------------------------------
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))


# ---------------------------------------------------------------------------
# Schema DDL — mirrors init-db.sh + migrate-db.py exactly
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys = ON;

-- journal_entries (init-db.sh + migrate-db.py unique constraint)
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    content TEXT,
    mood TEXT,
    energy TEXT,
    icor_elements TEXT DEFAULT '[]',
    summary TEXT,
    sentiment_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);

-- action_items (init-db.sh + migrate-db.py delegated + push_attempted_at)
CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    source_file TEXT,
    source_date TEXT,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_progress', 'completed', 'cancelled', 'pushed_to_notion', 'delegated')),
    icor_element TEXT,
    icor_project TEXT,
    external_id TEXT,
    external_system TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    delegated_to TEXT,
    push_attempted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON action_items(status);
CREATE INDEX IF NOT EXISTS idx_actions_date ON action_items(source_date);
CREATE INDEX IF NOT EXISTS idx_actions_icor ON action_items(icor_element);

-- concept_metadata (init-db.sh + migrate-db.py notion_id)
CREATE TABLE IF NOT EXISTS concept_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    file_path TEXT,
    status TEXT DEFAULT 'seedling' CHECK(status IN ('seedling', 'growing', 'evergreen')),
    icor_elements TEXT DEFAULT '[]',
    first_mentioned TEXT,
    last_mentioned TEXT,
    mention_count INTEGER DEFAULT 0,
    related_concepts TEXT DEFAULT '[]',
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    notion_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_concept_status ON concept_metadata(status);
CREATE INDEX IF NOT EXISTS idx_concept_title ON concept_metadata(title);

-- icor_hierarchy (init-db.sh)
CREATE TABLE IF NOT EXISTS icor_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL CHECK(level IN ('dimension', 'key_element', 'goal', 'project', 'habit')),
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES icor_hierarchy(id),
    description TEXT,
    status TEXT,
    notion_page_id TEXT,
    attention_score REAL DEFAULT 0,
    last_mentioned TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_icor_level ON icor_hierarchy(level);
CREATE INDEX IF NOT EXISTS idx_icor_parent ON icor_hierarchy(parent_id);
CREATE INDEX IF NOT EXISTS idx_icor_notion ON icor_hierarchy(notion_page_id);

-- attention_indicators (init-db.sh)
CREATE TABLE IF NOT EXISTS attention_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icor_element_id INTEGER NOT NULL REFERENCES icor_hierarchy(id),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    mention_count INTEGER DEFAULT 0,
    journal_days INTEGER DEFAULT 0,
    attention_score REAL DEFAULT 0,
    flagged INTEGER DEFAULT 0,
    calculated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attention_element ON attention_indicators(icor_element_id);
CREATE INDEX IF NOT EXISTS idx_attention_period ON attention_indicators(period_start, period_end);

-- vault_sync_log (init-db.sh)
CREATE TABLE IF NOT EXISTS vault_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    source_file TEXT,
    target TEXT,
    status TEXT DEFAULT 'success' CHECK(status IN ('success', 'failed', 'skipped')),
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sync_operation ON vault_sync_log(operation);
CREATE INDEX IF NOT EXISTS idx_sync_created ON vault_sync_log(created_at);

-- sync_state (migrate-db.py)
CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL UNIQUE,
    last_synced_at TEXT,
    items_synced INTEGER DEFAULT 0,
    last_sync_direction TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- classifications (migrate-db.py)
CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_text TEXT NOT NULL,
    message_ts TEXT,
    primary_dimension TEXT,
    confidence REAL,
    method TEXT,
    all_scores_json TEXT,
    user_correction TEXT,
    corrected_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_classifications_dim ON classifications(primary_dimension);
CREATE INDEX IF NOT EXISTS idx_classifications_method ON classifications(method);

-- keyword_feedback (migrate-db.py)
CREATE TABLE IF NOT EXISTS keyword_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension TEXT NOT NULL,
    keyword TEXT NOT NULL,
    source TEXT DEFAULT 'seed',
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(dimension, keyword)
);
CREATE INDEX IF NOT EXISTS idx_keyword_fb_dim ON keyword_feedback(dimension);

-- vault_index (migrate-db.py)
CREATE TABLE IF NOT EXISTS vault_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    type TEXT DEFAULT '',
    frontmatter_json TEXT DEFAULT '{}',
    outgoing_links_json TEXT DEFAULT '[]',
    incoming_links_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    word_count INTEGER DEFAULT 0,
    last_modified TEXT,
    indexed_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_index(title);
CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_index(type);

-- scheduler_state (migrate-db.py)
CREATE TABLE IF NOT EXISTS scheduler_state (
    job_name TEXT PRIMARY KEY,
    last_run_at TEXT,
    next_run_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

_SEED_SYNC_STATE = """
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('tasks');
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('projects');
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('goals');
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('tags');
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('notes');
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('concepts');
INSERT OR IGNORE INTO sync_state (entity_type) VALUES ('people');
"""

_SEED_ICOR = """
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(1, 'dimension', 'Health & Vitality', NULL, 'Physical and mental wellbeing'),
(2, 'dimension', 'Wealth & Finance', NULL, 'Financial health'),
(3, 'dimension', 'Relationships', NULL, 'People and social connections'),
(4, 'dimension', 'Mind & Growth', NULL, 'Learning and development'),
(5, 'dimension', 'Purpose & Impact', NULL, 'Mission and contribution'),
(6, 'dimension', 'Systems & Environment', NULL, 'Home, tools, workflows');

INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(101, 'key_element', 'Fitness', 1, 'Exercise'),
(102, 'key_element', 'Nutrition', 1, 'Diet'),
(201, 'key_element', 'Income', 2, 'Primary income'),
(301, 'key_element', 'Family', 3, 'Family relationships');
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_db(tmp_path):
    """Create an in-memory-style SQLite database (actually a temp file for
    aiosqlite compat) with the full schema seeded.

    Yields the Path to the temp database file.
    """
    db_file = tmp_path / "test_brain.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_SCHEMA_SQL)
    conn.executescript(_SEED_SYNC_STATE)
    conn.executescript(_SEED_ICOR)
    conn.commit()
    conn.close()
    return db_file


@pytest.fixture()
def temp_vault(tmp_path):
    """Create a temporary vault directory with a Daily Note template.

    Yields the Path to the vault root.
    """
    vault = tmp_path / "vault"
    vault.mkdir()

    # Create required subdirectories
    (vault / "Templates").mkdir()
    (vault / "Daily Notes").mkdir()
    (vault / "Inbox").mkdir()
    (vault / "Reports").mkdir()
    (vault / "Concepts").mkdir()
    (vault / "Projects").mkdir()
    (vault / "Dimensions").mkdir()
    (vault / "Identity").mkdir()

    # Write a Daily Note template
    template = (
        "---\n"
        "type: journal\n"
        "date: {{date:YYYY-MM-DD}}\n"
        "---\n"
        "\n"
        "# {{date:dddd, MMMM D, YYYY}}\n"
        "\n"
        "## Morning\n"
        "\n"
        "## Log\n"
        "\n"
        "## Evening\n"
    )
    (vault / "Templates" / "Daily Note.md").write_text(template, encoding="utf-8")

    return vault


@pytest.fixture()
def mock_config(test_db, temp_vault):
    """Patch config module globals to point at the test DB and temp vault.

    This must be used by tests that import modules referencing config.VAULT_PATH
    or config.DB_PATH.
    """
    with (
        patch("config.VAULT_PATH", temp_vault),
        patch("config.DB_PATH", test_db),
    ):
        yield {"db_path": test_db, "vault_path": temp_vault}

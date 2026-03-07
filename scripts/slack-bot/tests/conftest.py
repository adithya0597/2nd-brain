"""Shared fixtures for Second Brain Slack bot tests."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: add the slack-bot directory to sys.path so we can import config,
# core.*, etc. as the bot itself does.
# ---------------------------------------------------------------------------
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# ---------------------------------------------------------------------------
# Ensure config mock has required real attributes.
# Test files use sys.modules.setdefault("config", MagicMock()) independently.
# The first test file alphabetically wins, and others get auto-attributes.
# Fix: set critical attributes on whatever config mock exists.
# ---------------------------------------------------------------------------
_REQUIRED_DIMENSION_CHANNELS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}

_REQUIRED_DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness"],
    "Wealth & Finance": ["money", "finance"],
    "Relationships": ["friend", "family"],
    "Mind & Growth": ["learn", "read"],
    "Purpose & Impact": ["career", "mission"],
    "Systems & Environment": ["system", "automate"],
}


def _ensure_config_defaults():
    """Ensure the config mock in sys.modules has required real attributes.

    Always force-sets critical attributes (DIMENSION_KEYWORDS, DIMENSION_CHANNELS)
    to prevent test contamination from module-level mocking in individual test files.
    """
    cfg = sys.modules.get("config")
    if cfg is None:
        return
    # Always force-set critical attributes that tests depend on
    _FORCE_SET = {"DIMENSION_CHANNELS", "DIMENSION_KEYWORDS"}
    for attr, default in [
        ("CHANNELS", {
            "brain-inbox": "Raw capture and routing",
            "brain-daily": "Morning briefings, evening reviews, actions, projects, resources",
            "brain-insights": "Drift analysis, idea generation, pattern synthesis, and reflections",
            "brain-dashboard": "ICOR heatmap, project status, and cost tracking",
        }),
        ("DIMENSION_CHANNELS", _REQUIRED_DIMENSION_CHANNELS),
        ("DIMENSION_KEYWORDS", _REQUIRED_DIMENSION_KEYWORDS),
        ("PROJECT_KEYWORDS", ["project", "milestone"]),
        ("RESOURCE_KEYWORDS", ["article", "book"]),
        ("OWNER_SLACK_ID", ""),
        ("CONFIDENCE_THRESHOLD", 0.60),
        ("BOUNCER_TIMEOUT_MINUTES", 15),
        ("ANTHROPIC_API_KEY", ""),
        ("CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001"),
        ("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        ("EMBEDDING_DIM", 384),
    ]:
        if attr in _FORCE_SET:
            setattr(cfg, attr, default)
        else:
            val = getattr(cfg, attr, None)
            if val is None or isinstance(val, MagicMock):
                setattr(cfg, attr, default)


@pytest.fixture(autouse=True, scope="session")
def _fix_config_mock():
    """Session-scoped fixture to fix config mock attributes after all imports."""
    _ensure_config_defaults()
    yield



@pytest.fixture(autouse=True)
def _fix_config_per_test():
    """Per-test fixture to re-apply config defaults (in case a test replaces config)."""
    _ensure_config_defaults()
    yield


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

-- vault_nodes (migrate-db.py step 20 — replaces vault_index TABLE)
CREATE TABLE IF NOT EXISTS vault_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    type TEXT DEFAULT '',
    frontmatter_json TEXT DEFAULT '{}',
    tags_json TEXT DEFAULT '[]',
    word_count INTEGER DEFAULT 0,
    last_modified TEXT,
    indexed_at TEXT DEFAULT (datetime('now')),
    node_type TEXT DEFAULT 'document' CHECK(node_type IN ('document', 'icor_dimension', 'icor_element', 'concept', 'tag')),
    community_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_nodes(title);
CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_nodes(type);
CREATE INDEX IF NOT EXISTS idx_vault_node_type ON vault_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_vault_community ON vault_nodes(community_id);

-- vault_edges (migrate-db.py step 20)
CREATE TABLE IF NOT EXISTS vault_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node_id INTEGER NOT NULL,
    target_node_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL CHECK(edge_type IN ('wikilink', 'tag_shared', 'semantic_similarity', 'icor_affinity')),
    weight REAL DEFAULT 1.0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_node_id, target_node_id, edge_type),
    FOREIGN KEY (source_node_id) REFERENCES vault_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_node_id) REFERENCES vault_nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ve_source ON vault_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_ve_target ON vault_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_ve_type ON vault_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_ve_source_type ON vault_edges(source_node_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_ve_target_type ON vault_edges(target_node_id, edge_type);

-- vault_index VIEW (backward-compatible with old vault_index TABLE)
CREATE VIEW IF NOT EXISTS vault_index AS
SELECT n.id, n.file_path, n.title, n.type, n.frontmatter_json,
    COALESCE((SELECT json_group_array(t.title) FROM vault_edges e
              JOIN vault_nodes t ON e.target_node_id=t.id
              WHERE e.source_node_id=n.id AND e.edge_type='wikilink'),'[]') AS outgoing_links_json,
    COALESCE((SELECT json_group_array(s.file_path) FROM vault_edges e
              JOIN vault_nodes s ON e.source_node_id=s.id
              WHERE e.target_node_id=n.id AND e.edge_type='wikilink'),'[]') AS incoming_links_json,
    n.tags_json, n.word_count, n.last_modified, n.indexed_at
FROM vault_nodes n WHERE n.node_type='document';

-- scheduler_state (migrate-db.py)
CREATE TABLE IF NOT EXISTS scheduler_state (
    job_name TEXT PRIMARY KEY,
    last_run_at TEXT,
    next_run_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- api_token_logs (migrate-db.py step 12)
CREATE TABLE IF NOT EXISTS api_token_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cost_estimate_usd REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_token_logs_caller ON api_token_logs(caller);
CREATE INDEX IF NOT EXISTS idx_token_logs_created ON api_token_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_token_logs_model ON api_token_logs(model);
CREATE INDEX IF NOT EXISTS idx_token_logs_date_caller ON api_token_logs(created_at, caller);

-- embedding_state (migrate-db.py step 19)
CREATE TABLE IF NOT EXISTS embedding_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- vault_fts (migrate-db.py step 14)
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
    title, content, tags, file_path UNINDEXED
);

-- pending_captures (migrate-db.py step 15)
CREATE TABLE IF NOT EXISTS pending_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_text TEXT NOT NULL,
    message_ts TEXT UNIQUE NOT NULL,
    channel_id TEXT NOT NULL,
    slack_user_id TEXT NOT NULL,
    all_scores_json TEXT NOT NULL,
    primary_dimension TEXT,
    primary_confidence REAL NOT NULL,
    method TEXT,
    bouncer_dm_ts TEXT,
    bouncer_dm_channel TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'timeout')),
    user_selection TEXT,
    resolved_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_captures(status);
CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_captures(created_at);

-- sync_outbox (migrate-db.py step 21)
CREATE TABLE IF NOT EXISTS sync_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT 'create'
        CHECK(operation IN ('create', 'update', 'delete')),
    payload_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'confirmed', 'failed', 'dead_letter')),
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    notion_page_id TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processing_at TEXT,
    confirmed_at TEXT,
    UNIQUE(entity_type, entity_id, operation)
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON sync_outbox(status);
CREATE INDEX IF NOT EXISTS idx_outbox_entity ON sync_outbox(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_outbox_created ON sync_outbox(created_at);

-- captures_log (migrate-db.py step 21)
CREATE TABLE IF NOT EXISTS captures_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_text TEXT NOT NULL,
    dimensions_json TEXT DEFAULT '[]',
    confidence REAL,
    method TEXT,
    is_actionable INTEGER DEFAULT 0,
    source_channel TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_captures_log_created ON captures_log(created_at);

-- notion_projects (migrate-db.py step 16)
CREATE TABLE IF NOT EXISTS notion_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notion_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    status TEXT,
    tag TEXT,
    goal TEXT,
    deadline TEXT,
    archived INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_np_status ON notion_projects(status);
CREATE INDEX IF NOT EXISTS idx_np_name ON notion_projects(name);

-- notion_goals (migrate-db.py step 17)
CREATE TABLE IF NOT EXISTS notion_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notion_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    status TEXT,
    tag TEXT,
    deadline TEXT,
    archived INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ng_status ON notion_goals(status);

-- notion_people (migrate-db.py step 18)
CREATE TABLE IF NOT EXISTS notion_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notion_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    relationship TEXT,
    email TEXT,
    phone TEXT,
    company TEXT,
    tags_json TEXT DEFAULT '[]',
    birthday TEXT,
    last_checkin TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_npe_name ON notion_people(name);

-- engagement_daily (migrate-db.py step 22a)
CREATE TABLE IF NOT EXISTS engagement_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    captures_count INTEGER DEFAULT 0,
    actionable_captures INTEGER DEFAULT 0,
    actions_created INTEGER DEFAULT 0,
    actions_completed INTEGER DEFAULT 0,
    actions_pending INTEGER DEFAULT 0,
    journal_entry_count INTEGER DEFAULT 0,
    journal_word_count INTEGER DEFAULT 0,
    avg_sentiment REAL DEFAULT 0.0,
    mood TEXT,
    energy TEXT,
    dimension_mentions_json TEXT DEFAULT '{}',
    vault_files_modified INTEGER DEFAULT 0,
    vault_files_created INTEGER DEFAULT 0,
    edges_created INTEGER DEFAULT 0,
    notion_items_synced INTEGER DEFAULT 0,
    engagement_score REAL DEFAULT 0.0,
    computed_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_engagement_date ON engagement_daily(date);

-- dimension_signals (migrate-db.py step 22b)
CREATE TABLE IF NOT EXISTS dimension_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    dimension TEXT NOT NULL,
    mentions INTEGER DEFAULT 0,
    captures INTEGER DEFAULT 0,
    actions_created INTEGER DEFAULT 0,
    actions_completed INTEGER DEFAULT 0,
    rolling_7d_mentions INTEGER DEFAULT 0,
    rolling_7d_captures INTEGER DEFAULT 0,
    rolling_30d_mentions INTEGER DEFAULT 0,
    momentum TEXT DEFAULT 'cold'
        CHECK(momentum IN ('hot', 'warm', 'cold', 'frozen')),
    momentum_score REAL DEFAULT 0.0,
    trend TEXT DEFAULT 'stable'
        CHECK(trend IN ('rising', 'stable', 'declining')),
    computed_at TEXT DEFAULT (datetime('now')),
    UNIQUE(date, dimension)
);
CREATE INDEX IF NOT EXISTS idx_ds_date ON dimension_signals(date);
CREATE INDEX IF NOT EXISTS idx_ds_dimension ON dimension_signals(dimension);

-- brain_level (migrate-db.py step 22c)
CREATE TABLE IF NOT EXISTS brain_level (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT UNIQUE NOT NULL,
    level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 10),
    consistency_score REAL DEFAULT 0.0,
    breadth_score REAL DEFAULT 0.0,
    depth_score REAL DEFAULT 0.0,
    growth_score REAL DEFAULT 0.0,
    momentum_score REAL DEFAULT 0.0,
    days_active INTEGER DEFAULT 0,
    total_captures INTEGER DEFAULT 0,
    total_actions_completed INTEGER DEFAULT 0,
    hot_dimensions INTEGER DEFAULT 0,
    frozen_dimensions INTEGER DEFAULT 0,
    computed_at TEXT DEFAULT (datetime('now'))
);

-- alerts (migrate-db.py step 22d)
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL
        CHECK(alert_type IN ('drift', 'stale_actions', 'neglected_dimension',
            'knowledge_gap', 'streak_break', 'engagement_drop')),
    severity TEXT NOT NULL DEFAULT 'info'
        CHECK(severity IN ('critical', 'warning', 'info')),
    dimension TEXT,
    title TEXT NOT NULL,
    details_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'active'
        CHECK(status IN ('active', 'dismissed', 'resolved')),
    dismissed_at TEXT,
    resolved_at TEXT,
    fingerprint TEXT UNIQUE,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);
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


@pytest.fixture()
def vault_graph_db(test_db):
    """test_db with sample vault graph nodes + edges populated."""
    conn = sqlite3.connect(str(test_db))
    conn.execute("PRAGMA foreign_keys=ON")

    # Insert sample nodes (all node_type='document')
    nodes = [
        ("Daily Notes/2026-03-01.md", "2026-03-01", "journal", '{}', '[]', 150, "2026-03-01T10:00:00"),
        ("Concepts/Fitness.md", "Fitness", "concept", '{}', '["health"]', 200, "2026-03-01T10:00:00"),
        ("Concepts/Nutrition.md", "Nutrition", "concept", '{}', '["health"]', 180, "2026-03-01T10:00:00"),
        ("Identity/ICOR.md", "ICOR", "", '{}', '[]', 500, "2026-03-01T10:00:00"),
        ("Projects/Side-Project.md", "Side-Project", "project", '{}', '["dev"]', 300, "2026-03-01T10:00:00"),
    ]
    for fp, title, typ, fm, tags, wc, lm in nodes:
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, frontmatter_json, tags_json, word_count, last_modified) VALUES (?,?,?,?,?,?,?)",
            (fp, title, typ, fm, tags, wc, lm),
        )

    # Insert edges (wikilinks)
    # Daily note links to Fitness and Nutrition
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 2, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 3, 'wikilink')")
    # Fitness links to Nutrition
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (2, 3, 'wikilink')")
    # ICOR links to Side-Project
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (4, 5, 'wikilink')")

    conn.commit()
    conn.close()
    return test_db

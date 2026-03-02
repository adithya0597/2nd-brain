#!/usr/bin/env bash
set -euo pipefail

# AI-Powered Local Second Brain — Database Initialization
# Run from project root: ./scripts/init-db.sh

DB_PATH="data/brain.db"

if ! command -v sqlite3 &> /dev/null; then
    echo "Error: sqlite3 is required but not installed."
    exit 1
fi

mkdir -p data

echo "Initializing Second Brain database at $DB_PATH..."

sqlite3 "$DB_PATH" <<'SQL'

-- Journal entries from daily notes
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    mood TEXT,
    energy TEXT,
    icor_elements TEXT DEFAULT '[]',  -- JSON array of Key Element names
    summary TEXT,
    sentiment_score REAL,
    file_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);
CREATE INDEX IF NOT EXISTS idx_journal_file ON journal_entries(file_path);

-- Action items extracted from journal entries and meetings
CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    source_file TEXT,
    source_date TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'cancelled', 'pushed_to_notion')),
    icor_element TEXT,
    icor_project TEXT,
    external_id TEXT,        -- Notion page ID or other external system ID
    external_system TEXT,    -- 'notion_tasks', 'todoist', etc.
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_actions_status ON action_items(status);
CREATE INDEX IF NOT EXISTS idx_actions_date ON action_items(source_date);
CREATE INDEX IF NOT EXISTS idx_actions_icor ON action_items(icor_element);

-- Metadata for graduated concept notes
CREATE TABLE IF NOT EXISTS concept_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    file_path TEXT,
    status TEXT DEFAULT 'seedling' CHECK(status IN ('seedling', 'growing', 'evergreen')),
    icor_elements TEXT DEFAULT '[]',  -- JSON array
    first_mentioned TEXT,
    last_mentioned TEXT,
    mention_count INTEGER DEFAULT 0,
    related_concepts TEXT DEFAULT '[]',  -- JSON array of concept titles
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_concept_status ON concept_metadata(status);
CREATE INDEX IF NOT EXISTS idx_concept_title ON concept_metadata(title);

-- ICOR hierarchy: dimensions > key elements > goals > projects
CREATE TABLE IF NOT EXISTS icor_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL CHECK(level IN ('dimension', 'key_element', 'goal', 'project', 'habit')),
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES icor_hierarchy(id),
    description TEXT,
    status TEXT,
    notion_page_id TEXT,     -- Notion page ID for syncing
    attention_score REAL DEFAULT 0,
    last_mentioned TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_icor_level ON icor_hierarchy(level);
CREATE INDEX IF NOT EXISTS idx_icor_parent ON icor_hierarchy(parent_id);
CREATE INDEX IF NOT EXISTS idx_icor_notion ON icor_hierarchy(notion_page_id);

-- Attention indicators for tracking focus across ICOR elements
CREATE TABLE IF NOT EXISTS attention_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icor_element_id INTEGER NOT NULL REFERENCES icor_hierarchy(id),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    mention_count INTEGER DEFAULT 0,
    journal_days INTEGER DEFAULT 0,
    attention_score REAL DEFAULT 0,
    flagged INTEGER DEFAULT 0,  -- 1 if neglected
    calculated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_attention_element ON attention_indicators(icor_element_id);
CREATE INDEX IF NOT EXISTS idx_attention_period ON attention_indicators(period_start, period_end);

-- Sync log for tracking vault <-> Notion synchronization
CREATE TABLE IF NOT EXISTS vault_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,  -- 'push_task', 'pull_project', 'push_icor', 'pull_goal', etc.
    source_file TEXT,
    target TEXT,              -- Notion page ID or file path
    status TEXT DEFAULT 'success' CHECK(status IN ('success', 'failed', 'skipped')),
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sync_operation ON vault_sync_log(operation);
CREATE INDEX IF NOT EXISTS idx_sync_created ON vault_sync_log(created_at);

-- Seed ICOR Hierarchy: Dimensions
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(1, 'dimension', 'Health & Vitality', NULL, 'Physical and mental wellbeing'),
(2, 'dimension', 'Wealth & Finance', NULL, 'Financial health, career advancement, and income generation'),
(3, 'dimension', 'Relationships', NULL, 'People, community, and social connections'),
(4, 'dimension', 'Mind & Growth', NULL, 'Learning, intellectual development, and creative pursuits'),
(5, 'dimension', 'Purpose & Impact', NULL, 'Mission, contribution, and legacy'),
(6, 'dimension', 'Systems & Environment', NULL, 'Home, tools, workflows, and infrastructure');

-- Seed ICOR Hierarchy: Key Elements
-- Health & Vitality (parent_id = 1)
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(101, 'key_element', 'Fitness', 1, 'Exercise, strength training, cardio, flexibility'),
(102, 'key_element', 'Nutrition', 1, 'Diet quality, meal planning, supplements'),
(103, 'key_element', 'Sleep', 1, 'Sleep hygiene, recovery, energy management'),
(104, 'key_element', 'Mental Health', 1, 'Stress management, mindfulness, therapy, emotional regulation');

-- Wealth & Finance (parent_id = 2)
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(201, 'key_element', 'Income', 2, 'Primary income, salary growth, compensation'),
(202, 'key_element', 'Investments', 2, 'Portfolio management, asset allocation, financial planning'),
(203, 'key_element', 'Career Growth', 2, 'Skills development, promotions, professional reputation'),
(204, 'key_element', 'Side Projects', 2, 'Entrepreneurial ventures, freelance work, passive income');

-- Relationships (parent_id = 3)
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(301, 'key_element', 'Family', 3, 'Family relationships, quality time, support'),
(302, 'key_element', 'Friendships', 3, 'Close friendships, social activities, community'),
(303, 'key_element', 'Professional Network', 3, 'Mentors, colleagues, industry connections'),
(304, 'key_element', 'Romance', 3, 'Romantic relationships, partnership, dating');

-- Mind & Growth (parent_id = 4)
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(401, 'key_element', 'Reading', 4, 'Books, articles, research papers'),
(402, 'key_element', 'Skill Acquisition', 4, 'New skills, deliberate practice, courses'),
(403, 'key_element', 'Education', 4, 'Formal/informal education, certifications'),
(404, 'key_element', 'Creativity', 4, 'Creative projects, writing, art, music');

-- Purpose & Impact (parent_id = 5)
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(501, 'key_element', 'Personal Brand', 5, 'Online presence, thought leadership, reputation'),
(502, 'key_element', 'Content Creation', 5, 'Blog posts, videos, social media, newsletters'),
(503, 'key_element', 'Mentoring', 5, 'Teaching, advising, helping others grow'),
(504, 'key_element', 'Giving Back', 5, 'Volunteering, philanthropy, community service');

-- Systems & Environment (parent_id = 6)
INSERT OR IGNORE INTO icor_hierarchy (id, level, name, parent_id, description) VALUES
(601, 'key_element', 'Productivity Systems', 6, 'Task management, note-taking, automation'),
(602, 'key_element', 'Home Management', 6, 'Living space, organization, maintenance'),
(603, 'key_element', 'Digital Tools', 6, 'Software, hardware, tech stack');

SQL

echo ""
echo "Database initialized successfully!"
echo ""
echo "Tables created:"
sqlite3 "$DB_PATH" ".tables"
echo ""
echo "ICOR Hierarchy seeded:"
sqlite3 "$DB_PATH" "SELECT level, name FROM icor_hierarchy ORDER BY id;"

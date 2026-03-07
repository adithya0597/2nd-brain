#!/usr/bin/env python3
"""One-time migration: add sync_state table and concept_metadata.notion_id column."""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "brain.db" if len(sys.argv) < 2 else Path(sys.argv[1])


def migrate(db_path: Path = DB_PATH):
    """Run all migrations."""
    if not db_path.exists():
        print(f"Database not found at {db_path}. Creating new database.")

    conn = sqlite3.connect(str(db_path))
    # Apply all PRAGMAs consistently (matches core/db_connection.py)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    cursor = conn.cursor()

    # 1. Create sync_state table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL UNIQUE,
            last_synced_at TEXT,
            items_synced INTEGER DEFAULT 0,
            last_sync_direction TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # 2. Seed entity types
    entity_types = ["tasks", "projects", "goals", "tags", "notes", "concepts", "people"]
    for et in entity_types:
        cursor.execute(
            "INSERT OR IGNORE INTO sync_state (entity_type) VALUES (?)", (et,)
        )

    # 3. Add notion_id column to concept_metadata (if it doesn't exist)
    cursor.execute("PRAGMA table_info(concept_metadata)")
    columns = [row[1] for row in cursor.fetchall()]
    if "notion_id" not in columns:
        cursor.execute("ALTER TABLE concept_metadata ADD COLUMN notion_id TEXT")
        print("Added notion_id column to concept_metadata")
    else:
        print("concept_metadata.notion_id column already exists")

    # 4. Add delegated_to column and 'delegated' status to action_items
    cursor.execute("PRAGMA table_info(action_items)")
    ai_columns = [row[1] for row in cursor.fetchall()]
    if "delegated_to" not in ai_columns:
        cursor.execute("ALTER TABLE action_items ADD COLUMN delegated_to TEXT")
        print("Added delegated_to column to action_items")
    else:
        print("action_items.delegated_to column already exists")

    # Update CHECK constraint by recreating table (SQLite limitation)
    # First check if 'delegated' is already in the constraint
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='action_items'"
    )
    create_sql = cursor.fetchone()[0]
    if "'delegated'" not in create_sql:
        cursor.executescript("""
            CREATE TABLE action_items_new (
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
                delegated_to TEXT
            );
            INSERT INTO action_items_new SELECT
                id, description, source_file, source_date, status,
                icor_element, icor_project, external_id, external_system,
                created_at, completed_at, delegated_to
            FROM action_items;
            DROP TABLE action_items;
            ALTER TABLE action_items_new RENAME TO action_items;
            CREATE INDEX IF NOT EXISTS idx_actions_status ON action_items(status);
            CREATE INDEX IF NOT EXISTS idx_actions_date ON action_items(source_date);
            CREATE INDEX IF NOT EXISTS idx_actions_icor ON action_items(icor_element);
        """)
        print("Updated action_items CHECK constraint to include 'delegated' status")
    else:
        print("action_items CHECK constraint already includes 'delegated'")

    # 5. Create classifications table (classification logging)
    cursor.execute("""
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
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_classifications_dim ON classifications(primary_dimension)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_classifications_method ON classifications(method)")
    print("classifications table: created/verified")

    # 6. Create keyword_feedback table (dynamic keyword learning)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS keyword_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dimension TEXT NOT NULL,
            keyword TEXT NOT NULL,
            source TEXT DEFAULT 'seed',
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(dimension, keyword)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_keyword_fb_dim ON keyword_feedback(dimension)")
    print("keyword_feedback table: created/verified")

    # 7. Create vault_index table (vault file graph index)
    cursor.execute("""
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
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_index(title)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_index(type)")
    print("vault_index table: created/verified")

    # 8. Ensure journal_entries has unique constraint on date
    cursor.execute("PRAGMA table_info(journal_entries)")
    je_columns = [row[1] for row in cursor.fetchall()]
    if not je_columns:
        # Table doesn't exist at all — create it
        cursor.execute("""
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
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date)")
        print("journal_entries table: created with unique date constraint")
    else:
        # Check if date column has unique constraint
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='journal_entries'")
        create_sql = cursor.fetchone()
        if create_sql and "UNIQUE" not in create_sql[0].upper().split("DATE")[0]:
            # Add unique index if not already there
            try:
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_date_unique ON journal_entries(date)")
                print("journal_entries: added unique index on date")
            except sqlite3.OperationalError:
                print("journal_entries: unique index already exists or conflict")
        else:
            print("journal_entries: date uniqueness verified")

    # 9. Add push_attempted_at column to action_items (Notion push idempotency)
    try:
        cursor.execute("ALTER TABLE action_items ADD COLUMN push_attempted_at TEXT")
        print("Added push_attempted_at column to action_items")
    except sqlite3.OperationalError:
        print("action_items.push_attempted_at column already exists")

    # 10. Add push_attempted_at column to journal_entries (Notion push idempotency)
    try:
        cursor.execute("ALTER TABLE journal_entries ADD COLUMN push_attempted_at TEXT")
        print("Added push_attempted_at column to journal_entries")
    except sqlite3.OperationalError:
        print("journal_entries.push_attempted_at column already exists")

    # 11. Create scheduler_state table (persist job timestamps across restarts)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_state (
            job_name TEXT PRIMARY KEY,
            last_run_at TEXT,
            next_run_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    print("scheduler_state table: created/verified")

    # 12. Create api_token_logs table (API cost tracking)
    cursor.execute("""
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
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_logs_caller ON api_token_logs(caller)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_logs_created ON api_token_logs(created_at)")
    print("api_token_logs table: created/verified")

    # 13. Add missing indexes for api_token_logs queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_logs_model ON api_token_logs(model)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_logs_date_caller ON api_token_logs(created_at, caller)")
    print("api_token_logs indexes: model + date_caller created/verified")

    # 14. Create FTS5 virtual table for full-text vault search
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
            title, content, tags, file_path UNINDEXED
        )
    """)
    print("vault_fts FTS5 table: created/verified")

    # 15. Create pending_captures table (confidence bouncer)
    cursor.execute("""
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
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_captures(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_captures(created_at)")
    print("pending_captures table: created/verified")

    # 16. Create notion_projects table (persist pulled Notion projects)
    cursor.execute("""
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
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_np_status ON notion_projects(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_np_name ON notion_projects(name)")
    print("notion_projects table: created/verified")

    # 17. Create notion_goals table (persist pulled Notion goals)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notion_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            status TEXT,
            tag TEXT,
            deadline TEXT,
            archived INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ng_status ON notion_goals(status)")
    print("notion_goals table: created/verified")

    # 18. Create notion_people table (persist pulled Notion people)
    cursor.execute("""
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
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_npe_name ON notion_people(name)")
    print("notion_people table: created/verified")

    # 19. Embedding infrastructure (sqlite-vec)
    # embedding_state: track model version and state
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embedding_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    print("embedding_state table: created/verified")

    # vec0 virtual tables require sqlite-vec extension
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_vault USING vec0(
                embedding float[384],
                +file_path TEXT,
                +title TEXT,
                +content_hash TEXT
            )
        """)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_icor USING vec0(
                embedding float[384],
                +dimension TEXT,
                +reference_text TEXT
            )
        """)
        print("vec_vault + vec_icor virtual tables: created/verified")
    except ImportError:
        print("sqlite-vec not installed — skipping vec0 virtual tables (non-critical)")
    except Exception as e:
        print(f"vec0 table creation failed (non-critical): {e}")

    conn.commit()
    conn.close()
    print(f"Migration complete on {db_path}")
    print(f"  - sync_state table: created/verified")
    print(f"  - Seeded {len(entity_types)} entity types")
    print(f"  - action_items: delegated_to column + CHECK constraint verified")
    print(f"  - classifications table: created/verified")
    print(f"  - keyword_feedback table: created/verified")
    print(f"  - vault_index table: created/verified")
    print(f"  - journal_entries: date uniqueness verified")
    print(f"  - action_items.push_attempted_at: idempotency column verified")
    print(f"  - scheduler_state table: created/verified")
    print(f"  - api_token_logs table: created/verified")
    print(f"  - pending_captures table: created/verified")


if __name__ == "__main__":
    migrate()

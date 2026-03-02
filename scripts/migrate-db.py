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

    conn.commit()
    conn.close()
    print(f"Migration complete on {db_path}")
    print(f"  - sync_state table: created/verified")
    print(f"  - Seeded {len(entity_types)} entity types")
    print(f"  - action_items: delegated_to column + CHECK constraint verified")


if __name__ == "__main__":
    migrate()

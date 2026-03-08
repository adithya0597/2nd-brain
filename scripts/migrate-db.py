#!/usr/bin/env python3
"""One-time migration: add sync_state table and concept_metadata.notion_id column."""
import json
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
    # After Step 20, vault_index is a VIEW over vault_nodes — skip table+index creation.
    cursor.execute(
        "SELECT type FROM sqlite_master WHERE name='vault_index'"
    )
    vi_obj = cursor.fetchone()
    if vi_obj and vi_obj[0] == "view":
        print("vault_index is a VIEW (post Step 20) — skipping table creation")
    else:
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
            chat_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
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

    # 20. Graph schema: vault_nodes + vault_edges (replaces vault_index table)
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vault_nodes'"
    )
    if cursor.fetchone():
        print("vault_nodes table already exists — skipping Step 20")
    else:
        print("Step 20: Creating vault_nodes + vault_edges graph schema...")

        # 20a. Create vault_nodes table
        cursor.execute("""
            CREATE TABLE vault_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                type TEXT DEFAULT '',
                frontmatter_json TEXT DEFAULT '{}',
                tags_json TEXT DEFAULT '[]',
                word_count INTEGER DEFAULT 0,
                last_modified TEXT,
                indexed_at TEXT DEFAULT (datetime('now')),
                node_type TEXT DEFAULT 'document'
                    CHECK(node_type IN (
                        'document','icor_dimension','icor_element','concept','tag'
                    )),
                community_id INTEGER
            )
        """)
        print("  vault_nodes table: created")

        # 20b. Create vault_edges table
        cursor.execute("""
            CREATE TABLE vault_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_node_id INTEGER NOT NULL
                    REFERENCES vault_nodes(id) ON DELETE CASCADE,
                target_node_id INTEGER NOT NULL
                    REFERENCES vault_nodes(id) ON DELETE CASCADE,
                edge_type TEXT NOT NULL
                    CHECK(edge_type IN (
                        'wikilink','tag_shared','semantic_similarity','icor_affinity'
                    )),
                weight REAL DEFAULT 1.0,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_node_id, target_node_id, edge_type)
            )
        """)
        print("  vault_edges table: created")

        # 20c. Create indexes
        cursor.execute(
            "CREATE INDEX idx_ve_source ON vault_edges(source_node_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_ve_target ON vault_edges(target_node_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_ve_type ON vault_edges(edge_type)"
        )
        cursor.execute(
            "CREATE INDEX idx_ve_source_type ON vault_edges(source_node_id, edge_type)"
        )
        cursor.execute(
            "CREATE INDEX idx_ve_target_type ON vault_edges(target_node_id, edge_type)"
        )
        cursor.execute(
            "CREATE INDEX idx_vn_node_type ON vault_nodes(node_type)"
        )
        cursor.execute(
            "CREATE INDEX idx_vn_community ON vault_nodes(community_id)"
        )
        print("  indexes: created")

        # 20d. Migrate data from vault_index TABLE (if it exists as a table)
        cursor.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE name='vault_index' AND type='table'"
        )
        has_vault_index_table = cursor.fetchone() is not None

        wikilink_edge_count = 0

        if has_vault_index_table:
            # Copy rows from vault_index into vault_nodes
            cursor.execute("""
                INSERT INTO vault_nodes
                    (file_path, title, type, frontmatter_json, tags_json,
                     word_count, last_modified, indexed_at)
                SELECT file_path, title, type, frontmatter_json, tags_json,
                       word_count, last_modified, indexed_at
                FROM vault_index
            """)
            migrated_count = cursor.rowcount
            print(f"  migrated {migrated_count} rows from vault_index -> vault_nodes")

            # 20e. Parse outgoing_links_json and create wikilink edges
            # Build a title -> node id lookup
            cursor.execute("SELECT id, title FROM vault_nodes")
            title_to_id = {}
            for row in cursor.fetchall():
                title_to_id[row[0]] = row[1]  # id -> title
            # Invert: title -> id
            title_to_id = {v: k for k, v in title_to_id.items()}

            cursor.execute(
                "SELECT id, title, outgoing_links_json FROM vault_index"
            )
            for row in cursor.fetchall():
                vi_id, vi_title, outgoing_json = row
                source_id = title_to_id.get(vi_title)
                if source_id is None:
                    continue
                try:
                    outgoing = json.loads(outgoing_json or "[]")
                except (json.JSONDecodeError, TypeError):
                    continue
                for link_title in outgoing:
                    target_id = title_to_id.get(link_title)
                    if target_id and target_id != source_id:
                        try:
                            cursor.execute(
                                "INSERT OR IGNORE INTO vault_edges "
                                "(source_node_id, target_node_id, edge_type, weight) "
                                "VALUES (?, ?, 'wikilink', 1.0)",
                                (source_id, target_id),
                            )
                            wikilink_edge_count += cursor.rowcount
                        except sqlite3.IntegrityError:
                            pass
            print(f"  created {wikilink_edge_count} wikilink edges from outgoing_links")

            # 20f. Drop the vault_index TABLE
            cursor.execute("DROP TABLE vault_index")
            print("  dropped vault_index table")

            # Drop old indexes that were on vault_index (they're gone with the table)
        else:
            print("  vault_index table not found — skipping data migration")

        # 20g. Create backward-compatible vault_index VIEW
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vault_index AS
            SELECT
                n.id,
                n.file_path,
                n.title,
                n.type,
                n.frontmatter_json,
                COALESCE(
                    (SELECT json_group_array(t.title)
                     FROM vault_edges e
                     JOIN vault_nodes t ON e.target_node_id = t.id
                     WHERE e.source_node_id = n.id AND e.edge_type = 'wikilink'),
                    '[]'
                ) AS outgoing_links_json,
                COALESCE(
                    (SELECT json_group_array(s.file_path)
                     FROM vault_edges e
                     JOIN vault_nodes s ON e.source_node_id = s.id
                     WHERE e.target_node_id = n.id AND e.edge_type = 'wikilink'),
                    '[]'
                ) AS incoming_links_json,
                n.tags_json,
                n.word_count,
                n.last_modified,
                n.indexed_at
            FROM vault_nodes n
            WHERE n.node_type = 'document'
        """)
        print("  vault_index VIEW: created (backward-compatible)")

        # 20h. Create indexes on vault_nodes that replace the old vault_index indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_vault_title ON vault_nodes(title)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_nodes(type)"
        )
        print("  idx_vault_title + idx_vault_type: created on vault_nodes")

        # 20i. Seed 6 ICOR dimension nodes
        icor_dimensions = [
            "Health & Vitality",
            "Wealth & Finance",
            "Relationships",
            "Mind & Growth",
            "Purpose & Impact",
            "Systems & Environment",
        ]
        for dim in icor_dimensions:
            cursor.execute(
                "INSERT OR IGNORE INTO vault_nodes "
                "(file_path, title, node_type) "
                "VALUES (?, ?, 'icor_dimension')",
                (f"icor://{dim}", dim),
            )
        print(f"  seeded {len(icor_dimensions)} ICOR dimension nodes")

        conn.commit()
        print("Step 20 complete: vault_nodes + vault_edges graph schema ready")

    # 21. Sync outbox + captures_log tables (Sprint 4)
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_outbox'"
    )
    if cursor.fetchone():
        print("sync_outbox table already exists — skipping Step 21")
    else:
        cursor.execute("""
            CREATE TABLE sync_outbox (
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
            )
        """)
        cursor.execute(
            "CREATE INDEX idx_outbox_status ON sync_outbox(status)"
        )
        cursor.execute(
            "CREATE INDEX idx_outbox_entity ON sync_outbox(entity_type, entity_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_outbox_created ON sync_outbox(created_at)"
        )
        print("sync_outbox table: created with indexes")

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='captures_log'"
    )
    if cursor.fetchone():
        print("captures_log table already exists — skipping")
    else:
        cursor.execute("""
            CREATE TABLE captures_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_text TEXT NOT NULL,
                dimensions_json TEXT DEFAULT '[]',
                confidence REAL,
                method TEXT,
                is_actionable INTEGER DEFAULT 0,
                source_channel TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cursor.execute(
            "CREATE INDEX idx_captures_log_created ON captures_log(created_at)"
        )
        print("captures_log table: created with indexes")

    conn.commit()
    print("Step 21 complete: sync_outbox + captures_log tables ready")

    # 22. Engagement + dimension signals + brain level + alerts (Sprint 5)
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='engagement_daily'"
    )
    if cursor.fetchone():
        print("engagement_daily table already exists — skipping Step 22")
    else:
        # 22a. engagement_daily — daily metric snapshot
        cursor.execute("""
            CREATE TABLE engagement_daily (
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
            )
        """)
        cursor.execute(
            "CREATE INDEX idx_engagement_date ON engagement_daily(date)"
        )
        print("engagement_daily table: created")

        # 22b. dimension_signals — per-dimension daily momentum
        cursor.execute("""
            CREATE TABLE dimension_signals (
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
            )
        """)
        cursor.execute(
            "CREATE INDEX idx_ds_date ON dimension_signals(date)"
        )
        cursor.execute(
            "CREATE INDEX idx_ds_dimension ON dimension_signals(dimension)"
        )
        print("dimension_signals table: created")

        # 22c. brain_level — monthly aggregate engagement
        cursor.execute("""
            CREATE TABLE brain_level (
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
            )
        """)
        print("brain_level table: created")

        # 22d. alerts — pattern-detected alerts
        cursor.execute("""
            CREATE TABLE alerts (
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
            )
        """)
        cursor.execute(
            "CREATE INDEX idx_alerts_status ON alerts(status)"
        )
        cursor.execute(
            "CREATE INDEX idx_alerts_type ON alerts(alert_type)"
        )
        cursor.execute(
            "CREATE INDEX idx_alerts_fingerprint ON alerts(fingerprint)"
        )
        print("alerts table: created")

        conn.commit()
        print("Step 22 complete: engagement + signals + brain_level + alerts")

    # 23. Upgrade vec0 tables from float[384] to float[512] (nomic-embed-text-v1.5)
    try:
        import sqlite_vec  # noqa: F811

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        # Check if already migrated via embedding_state marker
        cursor.execute(
            "SELECT value FROM embedding_state WHERE key = 'vec_dimension'"
        )
        row = cursor.fetchone()
        if row and row[0] == "512":
            print("vec0 tables already at 512 dimensions — skipping Step 23")
        else:
            print("Step 23: Upgrading vec0 tables from 384 to 512 dimensions...")

            # 23a. Drop existing vec0 tables (cannot ALTER virtual tables)
            cursor.execute("DROP TABLE IF EXISTS vec_vault")
            cursor.execute("DROP TABLE IF EXISTS vec_icor")
            print("  dropped vec_vault + vec_icor")

            # 23b. Recreate with 512-dim embeddings
            cursor.execute("""
                CREATE VIRTUAL TABLE vec_vault USING vec0(
                    embedding float[512],
                    +file_path TEXT,
                    +title TEXT,
                    +content_hash TEXT
                )
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE vec_icor USING vec0(
                    embedding float[512],
                    +dimension TEXT,
                    +reference_text TEXT
                )
            """)
            print("  recreated vec_vault + vec_icor with float[512]")

            # 23c. Clear embedding_state to force re-embedding on next boot
            cursor.execute("DELETE FROM embedding_state")
            print("  cleared embedding_state (will re-embed on next boot)")

            # 23d. Set migration marker
            cursor.execute(
                "INSERT OR REPLACE INTO embedding_state (key, value) "
                "VALUES ('vec_dimension', '512')"
            )

            conn.commit()
            print("Step 23 complete: vec0 tables recreated with 512 dimensions")

    except ImportError:
        print("sqlite-vec not installed — skipping Step 23 vec0 upgrade (non-critical)")
    except Exception as e:
        print(f"Step 23 vec0 upgrade failed (non-critical): {e}")

    # 24. Section-level chunking tables (vault_chunks + vec_chunks)
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vault_chunks'"
    )
    if cursor.fetchone():
        print("vault_chunks table already exists — skipping Step 24")
    else:
        print("Step 24: Creating vault_chunks + vec_chunks chunking schema...")

        # 24a. vault_chunks — section-level chunks of vault files
        cursor.execute("""
            CREATE TABLE vault_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL REFERENCES vault_nodes(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                chunk_number INTEGER NOT NULL,
                chunk_type TEXT CHECK(chunk_type IN ('whole_file', 'header_based', 'fixed_size')),
                start_line INTEGER,
                end_line INTEGER,
                word_count INTEGER DEFAULT 0,
                char_count INTEGER DEFAULT 0,
                section_header TEXT DEFAULT '',
                header_level INTEGER DEFAULT 0,
                content_hash TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                indexed_at TEXT,
                UNIQUE(node_id, chunk_number)
            )
        """)
        print("  vault_chunks table: created")

        # 24b. Indexes on vault_chunks
        cursor.execute(
            "CREATE INDEX idx_vc_node ON vault_chunks(node_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_vc_file_path ON vault_chunks(file_path)"
        )
        cursor.execute(
            "CREATE INDEX idx_vc_hash ON vault_chunks(content_hash)"
        )
        print("  vault_chunks indexes: created")

        # 24c. vec_chunks — vector embeddings for chunks (sqlite-vec)
        # NOTE: Cannot use "vec_chunks" because sqlite-vec reserves
        # "{table}_chunks" as an internal backing table for vec_vault.
        try:
            import sqlite_vec  # noqa: F811

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)

            cursor.execute("""
                CREATE VIRTUAL TABLE vec_chunks USING vec0(
                    embedding float[512]
                )
            """)
            print("  vec_chunks virtual table: created (512-dim)")
        except ImportError:
            print("  sqlite-vec not installed — skipping vec_chunks (non-critical)")
        except Exception as e:
            print(f"  vec_chunks creation failed (non-critical): {e}")

        conn.commit()
        print("Step 24 complete: vault_chunks + vec_chunks chunking schema ready")

    # 25. Metadata filtering indexes on vault_nodes
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_vn_last_modified'"
    )
    if cursor.fetchone():
        print("Metadata indexes already exist — skipping Step 25")
    else:
        cursor.execute(
            "CREATE INDEX idx_vn_last_modified ON vault_nodes(last_modified)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_vn_type_nonempty ON vault_nodes(type) WHERE type != ''"
        )
        conn.commit()
        print("Step 25 complete: metadata filtering indexes created")

    conn.close()
    print(f"\nMigration complete on {db_path}")
    print(f"  - sync_state table: created/verified")
    print(f"  - Seeded {len(entity_types)} entity types")
    print(f"  - action_items: delegated_to column + CHECK constraint verified")
    print(f"  - classifications table: created/verified")
    print(f"  - keyword_feedback table: created/verified")
    print(f"  - vault_nodes + vault_edges: graph schema created/verified")
    print(f"  - vault_index VIEW: backward-compatible view created/verified")
    print(f"  - journal_entries: date uniqueness verified")
    print(f"  - action_items.push_attempted_at: idempotency column verified")
    print(f"  - scheduler_state table: created/verified")
    print(f"  - api_token_logs table: created/verified")
    print(f"  - pending_captures table: created/verified")
    print(f"  - sync_outbox + captures_log tables: created/verified")
    print(f"  - engagement + signals + brain_level + alerts: created/verified")
    print(f"  - vec0 tables: upgraded to 512 dimensions (if sqlite-vec available)")
    print(f"  - vault_chunks + vec_chunks: section-level chunking created/verified")
    print(f"  - metadata filtering indexes: last_modified + type_nonempty created/verified")


if __name__ == "__main__":
    migrate()

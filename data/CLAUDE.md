# data/ — SQLite Database & Notion Registry

## Purpose

Local persistent storage for the Second Brain. The SQLite database indexes vault content for fast querying; the Notion registry caches synced entity mappings.

## Files

| File | Size | Description |
|---|---|---|
| `brain.db` | ~150 KB | SQLite database with 10 tables |
| `notion-registry.json` | ~6 KB | Cached Notion entity mappings (projects, goals, dimensions) |
| `README.md` | ~7 KB | Human-readable database documentation |

## Database Tables (10 total)

| Table | Key Columns | Written By | Queried By |
|---|---|---|---|
| `journal_entries` | date (unique), content, mood, energy, icor_elements (JSON), sentiment_score | `journal_indexer.py` | `context_loader.py`, `db_ops.py` |
| `action_items` | description, status (pending/in_progress/completed/cancelled/pushed_to_notion/delegated), icor_element, icor_project, delegated_to | `capture.py`, `commands.py`, `actions.py` | `context_loader.py`, `scheduled.py` |
| `concept_metadata` | title (unique), status (seedling/growing/evergreen), icor_elements (JSON), mention_count, notion_id | `vault_indexer.py`, `notion_sync.py` | `context_loader.py` |
| `icor_hierarchy` | level (dimension/key_element/goal/project/habit), name, parent_id (self-ref), attention_score, notion_page_id | `init-db.sh`, `notion_sync.py` | `context_loader.py`, `db_ops.py` |
| `attention_indicators` | icor_element_id (FK), period_start/end, mention_count, journal_days, attention_score, flagged | `refresh-dashboard` command | `context_loader.py`, `scheduled.py` |
| `vault_sync_log` | operation, source_file, target, status (success/failed/skipped) | `notion_sync.py` | Debugging/audit only |
| `sync_state` | entity_type (unique), last_synced_at, items_synced, last_sync_direction | `notion_sync.py` | `notion_sync.py` |
| `vault_index` | file_path (unique), title, type, outgoing_links_json, incoming_links_json, tags_json, word_count | `vault_indexer.py` | `context_loader.py` (graph queries) |
| `classifications` | message_text, message_ts, primary_dimension, confidence, method, user_correction | `capture.py` | `scheduled.py` (keyword expansion) |
| `keyword_feedback` | dimension + keyword (unique), source, success_count, fail_count | `feedback.py`, `scheduled.py` | `config.py` (load_dynamic_keywords) |

## Access Patterns

- **Async reads/writes**: All bot code uses `aiosqlite` via `core/db_ops.py`. Each background thread creates its own event loop.
- **Sync writes**: `migrate-db.py`, `init-db.sh`, `vault_indexer.py`, and `journal_indexer.py` use synchronous `sqlite3` directly.
- **JSON columns**: `icor_elements`, `outgoing_links_json`, `incoming_links_json`, `tags_json`, `frontmatter_json`, `all_scores_json`, `related_concepts` are all JSON text columns. Use `json_each()` for SQL queries.
- **Registry JSON**: `notion-registry.json` is a flat `{entity_type: {name: {notion_page_id, ...}}}` dict. Read by `context_loader.py`, written by `notion_sync.py`.

## Notion Registry Format

```json
{
  "projects": {"Project Name": {"notion_page_id": "uuid", "tag": "Dimension/Element"}},
  "goals": {"Goal Name": {"notion_page_id": "uuid", "tag": "Dimension/Element"}},
  "dimensions": {"Health & Vitality": {"notion_page_id": "uuid"}}
}
```

## Gotchas

- **No WAL mode**: The database uses default journal mode. Concurrent async readers from multiple threads work fine, but avoid concurrent writers. **Audit finding: enable `PRAGMA journal_mode=WAL` at startup to prevent `OperationalError: database is locked` under thread contention.**
- **FK enforcement disabled**: Foreign keys are declared in DDL (`REFERENCES icor_hierarchy(id)`) but SQLite ignores them by default. `PRAGMA foreign_keys = ON` is never called. FK constraints are documentation-only. **Audit: add pragma after every `connect()` call.**
- **`vault_index` wipe risk**: `vault_indexer.run_full_index()` does `DELETE FROM vault_index` then bulk INSERTs with no surrounding transaction. If killed mid-reindex, the table is empty. **Audit: wrap in `BEGIN`...`COMMIT`.**
- **Notion push TOCTOU race**: `create_page()` succeeds → crash before `update_action_external()` → next sync re-pushes → duplicate Notion task. **Audit: add `push_attempted_at` idempotency column.**
- **Journal sync window bug**: `update_sync_state()` advances `last_synced_at` even on partial failure, excluding failed entries from future sync queries via the `since` filter. **Audit: remove `since` filter, rely solely on `vault_sync_log`.**
- **`action_items` was rebuilt**: `migrate-db.py` drops and recreates `action_items` to update a CHECK constraint. This migration is destructive if interrupted.
- **`journal_entries.date` uniqueness**: Enforced by both a UNIQUE index and the `journal_indexer` upsert logic (INSERT OR REPLACE).
- **`icor_hierarchy` is seed data**: Dimensions and key elements are inserted by `init-db.sh`. Goals/projects are added by Notion sync.
- **`vault_index` is ephemeral**: Rebuilt entirely on each `vault_indexer.run_full_index()` run (daily 5am + on bot startup). Do not store permanent data here.
- **JSON-in-TEXT anti-pattern**: `icor_elements`, `outgoing_links_json`, `incoming_links_json`, `tags_json` are JSON strings in TEXT columns. SQL filtering requires application-layer parsing. Consider `json_each()` for queries.
- **Path**: All bot code resolves `DB_PATH` from `config.py`. Scripts use relative or arg-based paths. Always use absolute paths when querying manually: `sqlite3 data/brain.db`.

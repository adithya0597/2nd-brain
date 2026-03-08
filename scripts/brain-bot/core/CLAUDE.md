# scripts/brain-bot/core/ — Business Logic Modules

## Purpose

All non-handler logic lives here: classification, context assembly, database access, vault I/O, Notion sync, message formatting, graph operations, and search.

## Module Summary

| Module | Description |
|---|---|
| `__init__.py` | Re-exports public API from all core modules |
| `ai_client.py` | Async Anthropic client wrapper with prompt caching support |
| `alerts.py` | Alert/notification utilities for system events |
| `analytics.py` | Usage analytics and metrics tracking |
| `app_home_builder.py` | Builds Telegram app home / settings views |
| `article_fetcher.py` | Fetches and parses article content from URLs |
| `async_utils.py` | Thread pool executor for offloading sync work from async handlers |
| `classifier.py` | 4-tier hybrid classification: noise filter → keyword match → embedding similarity → LLM fallback |
| `community.py` | Community detection on the vault knowledge graph |
| `context_loader.py` | Assembles context for AI commands: SQL queries, vault files, graph traversal, Notion data |
| `dashboard_builder.py` | Builds ICOR dashboard with heatmaps, attention scores, and quick-action buttons |
| `db_connection.py` | Synchronous SQLite connection factory with WAL mode |
| `db_ops.py` | Async SQLite operations via `aiosqlite`. Generic `query()`/`execute()` + domain helpers |
| `dimension_signals.py` | Extracts ICOR dimension signals from text for classification |
| `embedding_store.py` | sqlite-vec backed vector store for vault file embeddings |
| `engagement.py` | Engagement analysis and scoring |
| `formatter.py` | Telegram HTML message builders for all message types (briefings, dashboards, actions, reports, errors). Returns HTML strings, not Slack Block Kit |
| `fts_index.py` | FTS5 full-text search index for vault content |
| `graph_cache.py` | TTL-based caching for graph query results |
| `graph_ops.py` | Graph schema management and ICOR node operations |
| `icor_affinity.py` | ICOR dimension affinity edge computation |
| `journal_indexer.py` | Parses daily notes for mood/energy/ICOR mentions, populates `journal_entries` table |
| `message_utils.py` | Telegram message splitting (respects HTML tags, 4096-char limit) and send helpers |
| `notion_client.py` | Async `notion-client` wrapper with token-bucket rate limiter (3 req/s) and exponential retry |
| `notion_mappers.py` | Pure transform functions between local dicts and Notion property formats. No I/O |
| `notion_sync.py` | Sync orchestrator: `NotionSync.run_full_sync()` and `run_selective_sync()` |
| `output_parser.py` | Parses structured Claude API responses into typed result objects |
| `search.py` | Hybrid search combining FTS5, vector similarity, and graph traversal |
| `sync_outbox.py` | Outbox pattern for reliable Notion sync delivery |
| `token_logger.py` | Anthropic API token usage tracking |
| `vault_indexer.py` | Scans vault `.md` files, extracts frontmatter/wikilinks/tags, builds `vault_index` table + graph queries |
| `vault_ops.py` | Vault file read/write: daily notes, inbox entries, concept files, reports, weekly plans |

## Dependency Graph

```
config.py
  |
  +-- db_connection.py (reads DB_PATH, WAL mode)
  +-- db_ops.py (uses db_connection)
  +-- vault_ops.py (reads VAULT_PATH)
  +-- classifier.py (reads DIMENSION_KEYWORDS, ANTHROPIC_*)
  +-- context_loader.py
  |     +-- db_ops.py
  |     +-- vault_ops.py
  |     +-- vault_indexer.py (graph queries)
  |     +-- config.py (NOTION_REGISTRY_PATH)
  +-- vault_indexer.py (reads VAULT_PATH, DB_PATH)
  +-- journal_indexer.py (reads VAULT_PATH, DB_PATH)
  +-- notion_client.py (standalone, takes token arg)
  +-- notion_mappers.py (standalone, no imports)
  +-- notion_sync.py
  |     +-- db_ops.py
  |     +-- notion_client.py
  |     +-- notion_mappers.py
  +-- formatter.py (standalone — returns HTML strings)
  +-- message_utils.py (Telegram message splitting)
  +-- dashboard_builder.py (db_ops, formatter)
  +-- async_utils.py (standalone thread pool)
  +-- search.py (fts_index, embedding_store, vault_indexer)
```

## Key Patterns

- **classifier.py**: Uses a `Classifier` singleton. Tiers escalate: noise check (regex) → keyword match (weighted, from `DIMENSION_KEYWORDS` + DB) → sentence-transformer embedding cosine similarity → Claude API (via `claude-haiku-4-5`). Lazy-loads the embedding model on first use. Results logged to `classifications` table.
- **context_loader.py**: Three dicts drive context assembly: `_COMMAND_QUERIES` (SQL per command), `_COMMAND_VAULT_FILES` (identity files per command), `_GRAPH_CONTEXT_COMMANDS` (graph traversal strategy per command). Also checks `_NOTION_CONTEXT_COMMANDS` to inject cached Notion data.
- **db_connection.py**: Synchronous SQLite connections with `PRAGMA journal_mode=WAL` for concurrent read safety. Used by sync code paths.
- **db_ops.py**: Async queries via `aiosqlite`. Handlers call these directly from async context.
- **formatter.py**: Returns Telegram HTML strings (not Slack Block Kit). Uses `<b>`, `<i>`, `<code>`, `<a href>` tags. Messages are split by `message_utils.py` if they exceed Telegram's 4096-char limit.
- **message_utils.py**: Splits long HTML messages at paragraph boundaries, respecting open/close tags. Provides `send_long_message()` helper for multi-part sends.
- **async_utils.py**: Provides `run_in_executor()` to offload sync/CPU-bound work (like embedding computation) to a `ThreadPoolExecutor`. Includes `shutdown()` for clean exit.
- **vault_indexer.py**: `run_full_index()` scans all `.md` files under `vault/`, extracts wikilinks to build a bidirectional link graph stored in `vault_index`. Query functions: `find_files_mentioning()`, `get_linked_files()`, `find_intersection_nodes()`.
- **journal_indexer.py**: `run_full_index()` scans `vault/Daily Notes/`, uses regex heuristics for mood/energy detection, keyword matching for ICOR element extraction. Upserts into `journal_entries` (unique on date).
- **notion_sync.py**: `SyncResult` dataclass tracks counts. `NotionSync` accepts optional `ai_client` for Claude-assisted mapping; falls back to heuristic matching without it. Uses `sync_state` table to track last sync per entity type.
- **search.py**: Hybrid search combining FTS5 text matching, sqlite-vec vector similarity, and graph traversal. Used by `/find` command.
- **embedding_store.py**: Uses `sqlite-vec` extension for KNN vector search. Stores BAAI/bge-small-en-v1.5 embeddings (384-dim) alongside vault file paths.

## Gotchas

- **Embedding model**: `classifier.py` lazy-loads `sentence-transformers` model on first embedding-tier use. First call takes 5-10 seconds. Model stays in memory.
- **Formatter returns HTML**: Unlike the old Slack formatter (Block Kit JSON), `formatter.py` returns plain HTML strings. Callers pass `parse_mode=ParseMode.HTML` to Telegram send methods.
- **Message splitting**: Telegram has a hard 4096-character limit per message. `message_utils.py` handles splitting. Always use `send_long_message()` for AI command output.
- **Graph context cap**: `_gather_graph_context()` caps at 15 files, and each file is truncated to 2000 chars, to avoid token overload in Claude API calls.
- **notion_mappers.py is pure**: All functions are stateless transforms. Safe to call from anywhere, no side effects.
- **Journal re-index after close-day**: `commands.py` calls `journal_indexer.run_full_index()` after writing the evening review to the daily note. This ensures the updated note is immediately queryable.
- **No shared event loop issues**: PTB v21 manages a single event loop. All async handlers run on it. Use `async_utils.run_in_executor()` for blocking calls instead of creating new loops.

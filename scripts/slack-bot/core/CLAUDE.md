# scripts/slack-bot/core/ — Business Logic Modules

## Purpose

All non-handler logic lives here: classification, context assembly, database access, vault I/O, Notion sync, and Slack message formatting.

## Module Summary

| Module | Lines | Description |
|---|---|---|
| `__init__.py` | ~35 | Re-exports public API from all core modules |
| `classifier.py` | ~350 | 4-tier hybrid classification: noise filter → keyword match → embedding similarity → Claude LLM fallback |
| `context_loader.py` | ~370 | Assembles context for AI commands: SQL queries, vault files, graph traversal, Notion data |
| `db_ops.py` | ~230 | Async SQLite operations via `aiosqlite`. Generic `query()`/`execute()` + domain helpers |
| `vault_ops.py` | ~280 | Vault file read/write: daily notes, inbox entries, concept files, reports, weekly plans |
| `vault_indexer.py` | ~250 | Scans vault `.md` files, extracts frontmatter/wikilinks/tags, builds `vault_index` table + graph queries |
| `journal_indexer.py` | ~200 | Parses daily notes for mood/energy/ICOR mentions, populates `journal_entries` table |
| `formatter.py` | ~550 | Slack Block Kit builders for all message types (briefings, dashboards, actions, reports, errors) |
| `notion_client.py` | ~130 | Async `notion-client` wrapper with token-bucket rate limiter (3 req/s) and exponential retry |
| `notion_mappers.py` | ~370 | Pure transform functions between local dicts and Notion property formats. No I/O. |
| `notion_sync.py` | ~1000 | Sync orchestrator: `NotionSync.run_full_sync()` and `run_selective_sync()`. Push/pull per entity type. |

## Dependency Graph

```
config.py
  |
  +-- db_ops.py (reads DB_PATH)
  +-- vault_ops.py (reads VAULT_PATH)
  +-- classifier.py (reads DIMENSION_KEYWORDS, ANTHROPIC_*)
  +-- context_loader.py
  |     +-- db_ops.py
  |     +-- vault_ops.py
  |     +-- vault_indexer.py (graph queries)
  |     +-- config.py (NOTION_REGISTRY_PATH)
  +-- vault_indexer.py (reads VAULT_PATH, DB_PATH)
  +-- journal_indexer.py (reads VAULT_PATH, DB_PATH, DIMENSION_CHANNELS)
  +-- notion_client.py (standalone, takes token arg)
  +-- notion_mappers.py (standalone, no imports)
  +-- notion_sync.py
  |     +-- db_ops.py
  |     +-- notion_client.py
  |     +-- notion_mappers.py
  +-- formatter.py (standalone, no imports)
```

## Key Patterns

- **classifier.py**: Uses a `Classifier` singleton. Tiers escalate: noise check (regex) → keyword match (weighted, from `DIMENSION_KEYWORDS` + DB) → sentence-transformer embedding cosine similarity → Claude API. Lazy-loads the embedding model on first use. Results logged to `classifications` table.
- **context_loader.py**: Three dicts drive context assembly: `_COMMAND_QUERIES` (SQL per command), `_COMMAND_VAULT_FILES` (identity files per command), `_GRAPH_CONTEXT_COMMANDS` (graph traversal strategy per command). Also checks `_NOTION_CONTEXT_COMMANDS` to inject cached Notion data.
- **db_ops.py**: All queries are async (`aiosqlite`). Callers in sync handlers create a new `asyncio.new_event_loop()` per thread.
- **vault_indexer.py**: `run_full_index()` scans all `.md` files under `vault/`, extracts wikilinks to build a bidirectional link graph stored in `vault_index`. Query functions: `find_files_mentioning()`, `get_linked_files()`, `find_intersection_nodes()`.
- **journal_indexer.py**: `run_full_index()` scans `vault/Daily Notes/`, uses regex heuristics for mood/energy detection, keyword matching for ICOR element extraction. Upserts into `journal_entries` (unique on date).
- **notion_sync.py**: `SyncResult` dataclass tracks counts. `NotionSync` accepts optional `ai_client` for Claude-assisted mapping; falls back to heuristic matching without it. Uses `sync_state` table to track last sync per entity type.

## Gotchas

- **Embedding model**: `classifier.py` lazy-loads `sentence-transformers` model on first embedding-tier use. First call takes 5-10 seconds. Model stays in memory.
- **Tier 3 uses wrong model**: `_tier_llm()` uses `config.ANTHROPIC_MODEL` (Sonnet) for a binary classification task. **Audit: route to `claude-haiku-4-5` for 95% cost reduction.** Also creates a new `anthropic.Anthropic()` client per call — use a singleton.
- **MCP instruction mismatch**: Prompt files (ideas.md, schedule.md) tell Claude to "Use Notion MCP tools" but the Slack bot execution path has no MCP access. **Audit: create Slack-specific prompt versions that reference pre-gathered context instead.**
- **No prompt caching**: Every command re-sends the full CLAUDE.md + command prompt (~5K tokens) at full input price. **Audit: add `cache_control: {"type": "ephemeral"}` for 60-80% cost reduction on repeated calls.**
- **Graph context cap**: `_gather_graph_context()` caps at 15 files, and each file is truncated to 2000 chars, to avoid token overload in Claude API calls.
- **No shared event loop**: Each background thread in handlers creates its own event loop. Do not assume a global loop exists.
- **N+1 in graph traversal**: `get_linked_files()` issues one query per frontier hop, then per-row queries for title resolution. O(N*hops) on large vaults.
- **LIKE on JSON blobs**: `find_files_mentioning()` uses `LIKE '%topic%'` on JSON text columns — full table scan, no index. Matches substrings (`"car"` matches `"career"`).
- **notion_mappers.py is pure**: All functions are stateless transforms. Safe to call from anywhere, no side effects.
- **Journal re-index after close-day**: `commands.py` calls `journal_indexer.run_full_index()` after writing the evening review to the daily note. This ensures the updated note is immediately queryable.

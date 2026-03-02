# /brain:sync-notion — Bidirectional Notion Sync

Synchronize data between the local vault/SQLite and the Notion "My assistant" workspace using the Python sync engine.

## How It Works

The sync runs as a **Python-native pipeline** via the `NotionSync` orchestrator (`scripts/slack-bot/core/notion_sync.py`). It uses the `notion-client` SDK for all Notion API operations — no MCP tools required.

### Prerequisites
- `NOTION_TOKEN` set in `.env` (Notion internal integration token)
- Integration must have access to all databases in "My assistant" workspace
- Run `python scripts/migrate-db.py` once to create the `sync_state` table

## Sync Pipeline (executed in order)

| Step | Entity | Direction | Description |
|---|---|---|---|
| 1 | ICOR Tags | Push | Create missing ICOR hierarchy elements in Notion Tags DB |
| 2 | Action Items | Push | Push pending actions (no external_id) to Notion Tasks DB |
| 3 | Task Status | Pull | Pull status changes from Notion back to local action_items |
| 4 | Projects | Pull | Pull active/ongoing/planned projects from Notion Projects DB |
| 5 | Goals | Pull | Pull non-achieved goals from Notion Goals DB |
| 6 | Journal Entries | Push (summary) | Push metadata + summary to Notion Notes DB (Type: Daily) |
| 7 | Concepts | Push | Push growing/evergreen concepts to Notion Notes DB |
| 8 | People | Pull | Pull recently edited contacts from Notion People DB |

### Post-sync
- Updates `vault/Identity/Active-Projects.md` with pulled project data
- Saves `data/notion-registry.json` atomically (`.tmp` → rename)
- Logs all operations to `vault_sync_log` table
- Updates `sync_state` timestamps per entity type

## Invocation

### Via Slack
```
/brain-sync                    # Full sync (all entities)
/brain-sync tasks,projects     # Selective sync (comma-separated)
```

### Via Scheduled Job
- Daily at 10pm (automatic, configured in `handlers/scheduled.py`)
- Posts to `#brain-daily` only on errors

### Via Claude Code CLI
This command can also be run interactively in Claude Code for debugging:

1. Read current sync state:
```sql
SELECT * FROM sync_state;
SELECT * FROM vault_sync_log ORDER BY synced_at DESC LIMIT 20;
```

2. Check registry:
```
Read data/notion-registry.json
```

3. For operations requiring MCP tools (e.g., manual Notion queries), use the Notion MCP tools directly:
```
Use notion-search to query the Tasks collection
Use notion-fetch to inspect a specific page
```

## Notion Database References
- Tasks: `collection://231fda46-1a19-8125-95f4-000ba3e22ea6`
- Projects: `collection://231fda46-1a19-8171-9b6d-000b3e3409be`
- Goals: `collection://231fda46-1a19-810f-b0ac-000bbab78a4a`
- Tags: `collection://231fda46-1a19-8195-8338-000b82b65137`
- Notes: `collection://231fda46-1a19-8139-a401-000b477c8cd0`
- People: `collection://231fda46-1a19-811c-ac4d-000b87d02a66`

## Hybrid Intelligence (Optional)

When `ANTHROPIC_API_KEY` is set, the sync engine uses Claude for edge cases:
- **Tag classification**: When a concept could map to multiple ICOR tags
- **Conflict resolution**: When both local and Notion have changes to bidirectional entities
- **Project-goal linking**: When new projects don't have explicit goal relations

When `ANTHROPIC_API_KEY` is not set, deterministic fallbacks are used (keyword matching, last-write-wins).

## Status Mapping
| Local | Notion |
|---|---|
| pending | To Do |
| in_progress | Doing |
| completed | Done |

## Troubleshooting

- **"NOTION_TOKEN not configured"**: Set `NOTION_TOKEN=ntn_...` in `.env`
- **Rate limit errors**: The client auto-retries 429s with exponential backoff (3 req/sec limit)
- **Missing sync_state table**: Run `python scripts/migrate-db.py`
- **Stale registry**: Delete `data/notion-registry.json` and re-sync to rebuild

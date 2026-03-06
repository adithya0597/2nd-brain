# scripts/slack-bot/ — Second Brain Slack Bot

## Purpose

A Python Slack bot using Bolt + Socket Mode that bridges Slack with the Obsidian vault, SQLite database, Anthropic API, and Notion. No public endpoint needed — all communication via WebSocket.

## Boot Sequence

1. `config.py` loads `.env`, resolves all paths relative to project root (`../../` from this dir)
2. `app.py` creates `slack_bolt.App`, registers owner-only middleware
3. `register_handlers()` imports and registers all handler modules
4. Dynamic keywords loaded from `keyword_feedback` DB table into classifier
5. `start_scheduler()` registers cron-like jobs, starts scheduler daemon thread
6. Vault + journal indexers run on startup (populates `vault_index` and `journal_entries`)
7. `SocketModeHandler.start()` connects to Slack via WebSocket

## Key Patterns

- **Owner-only middleware**: All events filtered by `OWNER_SLACK_ID` (single-user bot)
- **Background processing**: All AI commands `ack()` immediately, then spawn a `threading.Thread` for the actual work
- **Scheduler**: Uses `schedule` library in a daemon thread (30s poll interval)
- **Graceful shutdown**: SIGINT/SIGTERM handlers for clean exit
- **Lazy channel resolution**: Channel name-to-ID mapping cached on first command use

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | `xoxb-` bot token |
| `SLACK_APP_TOKEN` | Yes | `xapp-` token for Socket Mode |
| `SLACK_SIGNING_SECRET` | No | Request signing (not needed for Socket Mode) |
| `OWNER_SLACK_ID` | No | Restrict bot to single user. Empty = no restriction |
| `ANTHROPIC_API_KEY` | No | Required for AI commands. Bot starts without it |
| `ANTHROPIC_MODEL` | No | Default: `claude-sonnet-4-5-20250929` |
| `NOTION_TOKEN` | No | Required for `/brain-sync`. Notion internal integration token |

## Path Resolution

All paths resolved from `PROJECT_ROOT = Path(__file__).parent.parent.parent` (two levels up from `slack-bot/`):

| Config Var | Resolves To |
|---|---|
| `VAULT_PATH` | `vault/` |
| `DB_PATH` | `data/brain.db` |
| `COMMANDS_PATH` | `.claude/commands/brain/` |
| `CLAUDE_MD_PATH` | `CLAUDE.md` |
| `NOTION_REGISTRY_PATH` | `data/notion-registry.json` |

## Directory Structure

```
slack-bot/
  app.py            # Entry point, boot sequence
  config.py         # Env vars, paths, keyword dicts, Notion collection IDs
  core/             # Business logic modules (see core/CLAUDE.md)
  handlers/         # Slack event/command/action handlers (see handlers/CLAUDE.md)
  requirements.txt  # pip dependencies
  launchd/          # macOS LaunchAgent plist for auto-start
```

## Gotchas

- **Run from any directory**: The bot resolves all paths from `config.py`'s `__file__` location, so `python scripts/slack-bot/app.py` works from anywhere.
- **No async event loop**: Despite using `aiosqlite` and async Notion client, the bot runs sync Bolt. Background threads create their own `asyncio.new_event_loop()` per task.
- **ANTHROPIC_API_KEY optional**: The bot starts and handles captures/status without it. Only AI-powered slash commands fail.
- **Keyword learning**: `config.py` has seed keywords; `load_dynamic_keywords()` merges in learned keywords from the DB. The classifier is updated at startup.
- **Socket Mode only**: No HTTP server. The `SLACK_SIGNING_SECRET` is unused in this mode.

# scripts/brain-bot/ — Second Brain Telegram Bot

## Purpose

A Python Telegram bot using `python-telegram-bot` (PTB) v21 that bridges Telegram with the Obsidian vault, SQLite database, Anthropic API, and Notion. Uses long-polling (no webhook/public endpoint needed). A single Forum-enabled Telegram group replaces the previous Slack channel architecture.

## Boot Sequence

1. `config.py` loads `.env`, resolves all paths relative to project root (`../../` from this dir)
2. `app.py` creates `Application` via `ApplicationBuilder` with `concurrent_updates(8)`
3. `post_init()` callback runs after the Application is initialized:
   a. Registers bot commands with Telegram via `set_my_commands()`
   b. `register_all()` imports and registers all handler modules
   c. Dynamic keywords loaded from `keyword_feedback` DB table into classifier
   d. Vault + journal indexers run on startup (populates `vault_index` and `journal_entries`)
   e. FTS5 index populated
   f. Vector embeddings populated
   g. Graph schema + ICOR affinity + community detection initialized
   h. Scheduled jobs registered with PTB's `JobQueue`
   i. Health check runs (database, vault, API key, topics, owner)
4. `application.run_polling()` starts the event loop

## Key Patterns

- **Owner-only filter**: Custom `OwnerFilter(filters.MessageFilter)` checks `user.id == OWNER_TELEGRAM_ID` (single-user bot)
- **Edit-in-place progress**: AI commands send an initial "Processing..." message, then `edit_message_text()` to replace it with the final result (no separate ack mechanism needed)
- **Forum Topics**: The group chat uses Forum mode — each topic replaces a Slack channel. Topic thread IDs stored in `config.TOPICS` dict
- **JobQueue scheduling**: PTB's built-in `JobQueue` replaces the `schedule` library. Jobs registered via `run_daily()`, `run_repeating()`, etc.
- **Async-native**: PTB v21 is fully async. Handler coroutines use `async/await` directly. Background CPU-bound work offloaded via `core/async_utils.py` thread pool executor
- **Graceful shutdown**: `post_shutdown()` callback cleans up executor pool
- **Concurrent updates**: `ApplicationBuilder().concurrent_updates(8)` allows up to 8 handlers to run concurrently (replaces manual thread spawning)

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `OWNER_TELEGRAM_ID` | No | Restrict bot to single user (integer). Empty = no restriction |
| `GROUP_CHAT_ID` | No | Forum-enabled group chat ID (negative integer) |
| `ANTHROPIC_API_KEY` | No | Required for AI commands. Bot starts without it |
| `ANTHROPIC_MODEL` | No | Default: `claude-sonnet-4-5-20250929` |
| `CLASSIFIER_LLM_MODEL` | No | Default: `claude-haiku-4-5-20251001` |
| `NOTION_TOKEN` | No | Required for `/sync`. Notion internal integration token |
| `TOPIC_BRAIN_*` | No | Forum topic thread IDs (e.g., `TOPIC_BRAIN_INBOX=123`) |

## Path Resolution

All paths resolved from `PROJECT_ROOT = Path(__file__).parent.parent.parent` (two levels up from `brain-bot/`):

| Config Var | Resolves To |
|---|---|
| `VAULT_PATH` | `vault/` |
| `DB_PATH` | `data/brain.db` |
| `COMMANDS_PATH` | `.claude/commands/brain/` |
| `CLAUDE_MD_PATH` | `CLAUDE.md` |
| `NOTION_REGISTRY_PATH` | `data/notion-registry.json` |

## Directory Structure

```
brain-bot/
  app.py            # Entry point, boot sequence, owner filter
  config.py         # Env vars, paths, keyword dicts, topic mappings
  core/             # Business logic modules (see core/CLAUDE.md)
  handlers/         # Telegram command/message/callback handlers (see handlers/CLAUDE.md)
  requirements.txt  # pip dependencies
  launchd/          # macOS LaunchAgent plist for auto-start
  logs/             # Rotating log files (created at startup)
  .env.example      # Template for environment variables
```

## Gotchas

- **Run from any directory**: The bot resolves all paths from `config.py`'s `__file__` location, so `python scripts/brain-bot/app.py` works from anywhere.
- **Fully async**: PTB v21 is async-native. All handlers are coroutines. Sync DB operations use `core/async_utils.py` to run in a thread pool.
- **ANTHROPIC_API_KEY optional**: The bot starts and handles captures/status without it. Only AI-powered commands fail.
- **Keyword learning**: `config.py` has seed keywords; `load_dynamic_keywords()` merges in learned keywords from the DB. The classifier is updated at startup.
- **Topic IDs**: Forum topic thread IDs can be set via `TOPIC_BRAIN_*` env vars or populated at runtime. Missing topic IDs cause messages to fall back to the general group thread.
- **No webhook**: Uses `run_polling()` — no public endpoint or SSL certificate needed.
- **Health check on startup**: Verifies database, vault, API key, topic IDs, and owner configuration. Warnings logged for missing optional components.

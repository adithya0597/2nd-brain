# scripts/ — Setup & Migration Scripts

## Purpose

One-time and occasional scripts for initializing the database, setting up the Telegram bot, and running schema migrations. These are not part of the running bot; they prepare the environment.

## Key Files

| File | Purpose | When to Run |
|---|---|---|
| `init-db.sh` | Creates `data/brain.db` with all base tables (journal_entries, action_items, concept_metadata, icor_hierarchy, attention_indicators, vault_sync_log) | Once, on first setup |
| `migrate-db.py` | Adds newer tables (sync_state, classifications, keyword_feedback, vault_index, embeddings) and columns | After pulling new schema changes |
| `setup-telegram.py` | Interactive Telegram bot setup: verify token, detect owner, create forum group with topics, write `.env` | Once, on Telegram bot setup |
| `common-queries.sql` | Reference SQL patterns used by `/brain:*` commands | Not executed directly; reference only |
| `brain-bot/` | The running Telegram bot application (see `brain-bot/CLAUDE.md`) | Continuous process |

## Execution Order

1. `./scripts/init-db.sh` — create the database
2. `python scripts/migrate-db.py` — apply migrations
3. `python scripts/setup-telegram.py` — configure Telegram bot and create forum topics
4. Start the bot: `cd scripts/brain-bot && python app.py`

## Dependencies

- `sqlite3` CLI (for `init-db.sh`)
- Python 3.10+ (for `migrate-db.py`, `setup-telegram.py`)
- `TELEGRAM_BOT_TOKEN` from @BotFather (for setup script)
- No pip dependencies — setup scripts use only stdlib + `requests`

## Gotchas

- **init-db.sh vs migrate-db.py**: `init-db.sh` creates the original schema. `migrate-db.py` adds Phase 2+ tables. Run both on fresh installs; run only `migrate-db.py` on existing installs.
- **DB path**: `init-db.sh` uses relative path `data/brain.db` (run from project root). `migrate-db.py` resolves path from its own location. You can also pass a path as argv: `python migrate-db.py /path/to/brain.db`.
- **common-queries.sql**: Read-only reference. The actual queries live in `brain-bot/core/context_loader.py` as the `_COMMAND_QUERIES` dict.
- **migrate-db.py recreates action_items**: The migration rebuilds the `action_items` table to update a CHECK constraint. This is destructive if interrupted — do not kill mid-run.
- **setup-telegram.py**: Interactive script — prompts for bot token, verifies via `getMe`, auto-detects owner chat ID, creates forum topics. Run `python scripts/setup-telegram.py --help` for options.

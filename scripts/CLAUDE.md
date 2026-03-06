# scripts/ — Setup & Migration Scripts

## Purpose

One-time and occasional scripts for initializing the database, creating Slack channels, and running schema migrations. These are not part of the running bot; they prepare the environment.

## Key Files

| File | Purpose | When to Run |
|---|---|---|
| `init-db.sh` | Creates `data/brain.db` with all base tables (journal_entries, action_items, concept_metadata, icor_hierarchy, attention_indicators, vault_sync_log) | Once, on first setup |
| `migrate-db.py` | Adds newer tables (sync_state, classifications, keyword_feedback, vault_index) and columns (notion_id, delegated_to) | After pulling new schema changes |
| `setup-slack.sh` | Creates 15 `brain-*` Slack channels via API, sets topics/purposes, posts welcome messages | Once, on Slack app setup |
| `setup-slack.py` | Python equivalent of `setup-slack.sh` — also auto-joins bot to channels | Alternative to the shell version |
| `common-queries.sql` | Reference SQL patterns used by `/brain:*` commands | Not executed directly; reference only |
| `slack-bot/` | The running Slack bot application (see `slack-bot/CLAUDE.md`) | Continuous process |

## Execution Order

1. `./scripts/init-db.sh` — create the database
2. `python scripts/migrate-db.py` — apply migrations
3. `./scripts/setup-slack.sh` OR `python scripts/setup-slack.py` — create Slack channels
4. Start the bot: `cd scripts/slack-bot && python app.py`

## Dependencies

- `sqlite3` CLI (for `init-db.sh`)
- Python 3.10+ (for `migrate-db.py`, `setup-slack.py`)
- `SLACK_BOT_TOKEN` in `.env` (for Slack setup scripts)
- No pip dependencies — setup scripts use only stdlib

## Gotchas

- **init-db.sh vs migrate-db.py**: `init-db.sh` creates the original schema. `migrate-db.py` adds Phase 2+ tables. Run both on fresh installs; run only `migrate-db.py` on existing installs.
- **setup-slack.sh vs setup-slack.py**: Both are idempotent. The Python version also auto-joins channels. Use whichever you prefer.
- **DB path**: `init-db.sh` uses relative path `data/brain.db` (run from project root). `migrate-db.py` resolves path from its own location. You can also pass a path as argv: `python migrate-db.py /path/to/brain.db`.
- **common-queries.sql**: Read-only reference. The actual queries live in `slack-bot/core/context_loader.py` as the `_COMMAND_QUERIES` dict.
- **migrate-db.py recreates action_items**: The migration rebuilds the `action_items` table to update a CHECK constraint. This is destructive if interrupted — do not kill mid-run.

# Second Brain

An AI-powered Second Brain that auto-organizes thoughts so your real brain can just think. Drop notes into a frictionless inbox (Slack), and the AI handles classification, routing, analysis, and synthesis — turning passive notes into an active knowledge system.

## Features

- **ICOR Classification**: 4-tier hybrid pipeline (noise filter → keyword → embedding → LLM) routes captures to 6 life dimensions
- **16 Slash Commands**: Morning briefing, evening review, drift analysis, pattern emergence, semantic search, and more
- **Notion Sync**: Bidirectional sync with Ultimate Brain 3.0 workspace (tags, tasks, projects, goals, journals, concepts, people)
- **Obsidian Vault**: Auto-generated daily notes, concept files, project docs, and reports
- **Scheduled Automations**: 10 cron jobs for briefings, dashboards, drift reports, and reindexing
- **Cost Monitoring**: API token usage logging to SQLite for spend tracking

## Architecture

```
Slack (Socket Mode) → Bolt App → Handlers → Core Modules → SQLite + Vault + Notion
```

| Layer | Components |
|---|---|
| **Handlers** | capture, commands, actions, feedback, scheduled |
| **Core** | classifier, context_loader, db_ops, vault_ops, vault_indexer, journal_indexer, formatter, notion_sync, token_logger |
| **Storage** | SQLite (`data/brain.db`), Obsidian vault (`vault/`), Notion API |

## Quick Start

### Prerequisites

- Python 3.10+
- SQLite 3.35+
- Slack workspace with a bot app (Socket Mode enabled)
- Notion workspace (optional, for sync)

### 1. Clone and install

```bash
git clone <repo-url>
cd 2nd-brain
pip install -r scripts/slack-bot/requirements.txt
```

### 2. Environment setup

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | `xoxb-` bot token |
| `SLACK_APP_TOKEN` | Yes | `xapp-` token for Socket Mode |
| `OWNER_SLACK_ID` | No | Restrict bot to single user |
| `ANTHROPIC_API_KEY` | No | Required for AI commands |
| `ANTHROPIC_MODEL` | No | Default: `claude-sonnet-4-5-20250929` |
| `NOTION_TOKEN` | No | Required for Notion sync |

### 3. Initialize database

```bash
./scripts/init-db.sh
python scripts/migrate-db.py
```

### 4. Create Slack channels

```bash
python scripts/setup-slack.py
```

This creates 15 `brain-*` channels and sets topics/purposes.

### 5. Start the bot

```bash
cd scripts/slack-bot
python app.py
```

### 6. Auto-start (macOS)

```bash
cp scripts/slack-bot/launchd/com.brain.slack-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.brain.slack-bot.plist
```

### Verification checklist

After starting, verify:

1. Bot connects to Slack (check logs for "Socket Mode connected")
2. Health check passes at startup (schema, env vars, vault path validated)
3. `#brain-inbox` accepts messages and routes to dimension channels
4. `/brain-status` returns a dashboard in `#brain-dashboard`
5. `/brain-help` shows all available commands
6. `sqlite3 data/brain.db "SELECT count(*) FROM vault_index"` returns > 0

## Running Tests

```bash
cd scripts/slack-bot
python -m pytest tests/ -v
```

257 tests covering: classifier, vault operations, journal indexer, Notion sync, feedback routing, health check, token logger.

## Project Structure

```
2nd-brain/
├── CLAUDE.md              # Project instructions
├── AUDIT-REPORT.md        # System audit and improvement tracking
├── data/
│   ├── brain.db           # SQLite database (11 tables)
│   └── notion-registry.json
├── vault/                 # Obsidian vault
│   ├── Daily Notes/       # YYYY-MM-DD.md journals
│   ├── Identity/          # ICOR.md, Values.md, Active-Projects.md
│   ├── Concepts/          # Evergreen concept notes
│   ├── Reports/           # Auto-saved command outputs
│   └── ...
├── scripts/
│   ├── init-db.sh         # Create database
│   ├── migrate-db.py      # Apply migrations
│   ├── setup-slack.py     # Create Slack channels
│   └── slack-bot/         # The bot application
│       ├── app.py         # Entry point
│       ├── config.py      # Environment and paths
│       ├── core/          # Business logic
│       ├── handlers/      # Slack event handlers
│       └── tests/         # pytest suite (257 tests)
└── .claude/
    ├── commands/brain/    # AI command prompts
    └── skills/            # Skill definitions
```

## License

Private project.

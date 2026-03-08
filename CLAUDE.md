# Second Brain — Project Instructions

## Vault & Data Locations
- **Obsidian Vault:** `vault/`
- **SQLite Database:** `data/brain.db`
- **Notion Registry:** `data/notion-registry.json`
- **Templates:** `vault/Templates/`
- **Identity Files:** `vault/Identity/`

## ICOR → Ultimate Brain Mapping

The user's life is organized using the ICOR hierarchy, mapped to the existing Notion "Ultimate Brain 3.0" (Thomas Frank) workspace in "My assistant":

| ICOR Level | Ultimate Brain Equivalent | Notes |
|---|---|---|
| Dimension | Top-level Tag (Type: Area) | e.g., "Health & Vitality" |
| Key Element | Sub-Tag under Dimension (Type: Area) | e.g., "Fitness" under "Health & Vitality" |
| Goal | Goals DB entry (linked to Tag via `Tag` relation) | Status: Dream → Active → Achieved |
| Project | Projects DB entry (Status: Doing/Planned) | Linked to Goal and Tag |
| Habit/Routine | Projects DB entry (Status: Ongoing) | "Ongoing" = maintenance/habit |
| Resource | Tag (Type: Resource) | Reference material, tools |
| Archive | Archived checkbox on any entity | Built into every DB |

## Notion Database Collection IDs (Workspace: "My assistant")

| Database | Collection ID |
|---|---|
| Tasks | `collection://231fda46-1a19-8125-95f4-000ba3e22ea6` |
| Projects | `collection://231fda46-1a19-8171-9b6d-000b3e3409be` |
| Goals | `collection://231fda46-1a19-810f-b0ac-000bbab78a4a` |
| Tags | `collection://231fda46-1a19-8195-8338-000b82b65137` |
| Notes | `collection://231fda46-1a19-8139-a401-000b477c8cd0` |
| People | `collection://231fda46-1a19-811c-ac4d-000b87d02a66` |
| Milestones | `collection://231fda46-1a19-81f6-970a-000b8787ea1e` |
| Work Sessions | `collection://231fda46-1a19-8150-8994-000b98a48efa` |

## Key Notion Schema Notes

### Tasks DB
- **Name** (title), **Status** (To Do/Doing/Done), **Due** (date), **Project** (relation to Projects), **People** (relation), **Priority** (Low/Medium/High), **Energy** (High/Low), **Smart List** (Do Next/Delegated/Someday), **Description** (text), **My Day** (checkbox)
- Supports recurring tasks, sub-tasks, work sessions

### Projects DB
- **Name** (title), **Status** (Planned/On Hold/Doing/Ongoing/Done), **Tag** (relation to Tags, limit 1), **Goal** (relation to Goals, limit 1), **Target Deadline** (date), **Archived** (checkbox), **Tasks/Notes/People** (relations)

### Goals DB
- **Name** (title), **Status** (Dream/Active/Achieved), **Tag** (relation to Tags, limit 1), **Target Deadline** (date), **Milestones** (relation), **Projects** (relation), **Archived** (checkbox)

### Tags DB (PARA + ICOR)
- **Name** (title), **Type** (Area/Resource/Entity), **Parent Tag** (self-relation), **Sub-Tags** (self-relation), **Goals/Projects/Notes/People** (relations), **Archived** (checkbox), **Favorite** (checkbox)

### Notes DB
- **Name** (title), **Type** (Journal/Meeting/Web Clip/Lecture/Reference/Book/Idea/Plan/Recipe/Voice Note/Daily), **Tag** (relation to Tags), **Project** (relation), **People** (relation), **Note Date** (date), **Archived** (checkbox)

### People DB
- **Full Name** (title), **Relationship** (Family/Friend/Colleague/Client/Customer/Business Partner/Vendor/Senpai/Teacher), **Email**, **Phone**, **Company**, **Tags** (relation), **Projects/Notes/Tasks** (relations), **Pipeline Status**, **Birthday**, **Check-In**, **Last Check-In**

## Frontmatter Conventions

All vault markdown files use YAML frontmatter:
```yaml
---
type: journal | concept | meeting | project
date: YYYY-MM-DD
icor_elements: [Key Element names]
status: active | completed | archived  # for concepts: seedling | growing | evergreen
notion_id: <page-id>  # if synced to Notion
tags: [additional tags]
---
```

## File Naming Conventions
- Daily notes: `vault/Daily Notes/YYYY-MM-DD.md`
- Concepts: `vault/Concepts/Concept-Name.md` (title case, hyphens)
- Meetings: `vault/Meetings/YYYY-MM-DD-Meeting-Topic.md`
- Projects: `vault/Projects/Project-Name.md`

## Linking Conventions
- Use Obsidian `[[wikilinks]]` for internal vault links
- Use `[[Concept-Name]]` format for concept cross-references
- Daily notes link to concepts they discuss: `Discussed [[Concept-Name]] today`

## Available Commands

| Command | Description |
|---|---|
| `/brain:context-load` | Pre-load session context from identity files and SQLite |
| `/brain:today` | Morning review: create daily note, briefing, priorities |
| `/brain:close-day` | Evening review: extract actions, index entries, update attention |
| `/brain:graduate` | Promote recurring journal themes to concept notes |
| `/brain:trace` | Track evolution of a concept over time |
| `/brain:drift` | Compare stated goals vs actual journaling focus |
| `/brain:emerge` | Surface unnamed patterns from scattered notes |
| `/brain:challenge` | Red-team a belief with counter-evidence from vault |
| `/brain:ghost` | Answer a question as the user would (digital twin) |
| `/brain:connect` | Find serendipitous connections between two domains |
| `/brain:sync-notion` | Bidirectional sync with Notion workspace |
| `/brain:process-inbox` | Categorize and route inbox captures |
| `/brain:process-meeting` | Parse meeting transcript, extract actions, update CRM |
| `/brain:refresh-dashboard` | Recalculate attention scores, update Notion cockpit |
| `/brain:ideas` | Deep vault scan for actionable ideas across 5 categories |
| `/brain:schedule` | Energy-aware weekly planning with ICOR balance |
| `/brain:projects` | Active project dashboard with cross-dimensional tracking |
| `/brain:resources` | Knowledge base catalog with resource health metrics |

## SQLite Database

The local SQLite database at `data/brain.db` indexes vault content for fast querying. Use `sqlite3 data/brain.db` to query. Key tables: journal_entries, action_items, concept_metadata, icor_hierarchy, attention_indicators, vault_sync_log, vault_index, classifications, keyword_feedback, sync_state.

## Telegram Integration

A Python Telegram bot (`scripts/brain-bot/`) provides an asynchronous remote interface to the Second Brain via long-polling (no webhook or public endpoint needed). Built on `python-telegram-bot` (PTB) v21 with async handlers.

### Setup
1. Create a bot via @BotFather on Telegram, get the bot token
2. Run `python scripts/setup-telegram.py` — interactive setup that verifies the token, detects your user ID, creates a Forum-enabled group with topics, and writes `.env`
3. Run `python scripts/migrate-db.py` to prepare database tables
4. Install deps: `cd scripts/brain-bot && pip install -r requirements.txt`
5. Start: `python scripts/brain-bot/app.py`
6. Auto-start: `cp scripts/brain-bot/launchd/com.brain.telegram-bot.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.brain.telegram-bot.plist`

### Forum Topic Architecture

A single Telegram group with Forum Topics enabled replaces the previous multi-channel architecture. Each topic is a persistent thread within the group:

| Topic | Purpose |
|---|---|
| `brain-inbox` | Drop thoughts here — bot classifies and routes to vault + SQLite |
| `brain-daily` | Morning briefings (7am) and evening reviews (9pm) |
| `brain-actions` | Action items with Complete/Snooze/Delegate buttons |
| `brain-dashboard` | ICOR heatmap, attention scores, project status (6am/6pm) |
| `brain-ideas` | Idea generation reports |
| `brain-drift` | Alignment drift reports (weekly Sunday 6pm) |
| `brain-insights` | Pattern synthesis, ghost reflections, trace timelines |
| `brain-health` | Health & Vitality captures |
| `brain-wealth` | Wealth & Finance captures |
| `brain-relations` | Relationships captures |
| `brain-growth` | Mind & Growth captures |
| `brain-purpose` | Purpose & Impact captures |
| `brain-systems` | Systems & Environment captures |
| `brain-projects` | Active projects, weekly summaries (Mon 9am), cross-posted captures |
| `brain-resources` | Resource catalog, monthly digests (1st 10am), cross-posted captures |

### Telegram Bot Commands

| Command | Maps To | Output Topic |
|---|---|---|
| `/today` | `/brain:today` | brain-daily |
| `/close` | `/brain:close-day` | brain-daily |
| `/drift` | `/brain:drift` | brain-drift |
| `/emerge` | `/brain:emerge` | brain-insights |
| `/ideas` | `/brain:ideas` | brain-ideas |
| `/schedule` | `/brain:schedule` | brain-daily |
| `/ghost` | `/brain:ghost` | brain-insights |
| `/status` | Quick SQLite query | brain-dashboard |
| `/sync` | `/brain:sync-notion` | DM |
| `/projects` | `/brain:projects` | brain-projects |
| `/resources` | `/brain:resources` | brain-resources |
| `/trace` | `/brain:trace` | brain-insights |
| `/connect` | `/brain:connect` | brain-insights |
| `/challenge` | `/brain:challenge` | brain-insights |
| `/graduate` | `/brain:graduate` | brain-insights |
| `/context` | `/brain:context-load` | DM |
| `/find` | Hybrid semantic search | DM |
| `/help` | Command listing | DM |
| `/engage` | Engagement analysis | brain-insights |
| `/dashboard` | Full ICOR dashboard | brain-dashboard |

### Scheduled Automations

| Job | Topic | Schedule |
|---|---|---|
| Morning Briefing | brain-daily | Daily 7am CST |
| Evening Prompt | brain-daily | Daily 9pm CST |
| Dashboard Refresh | brain-dashboard | Daily 6am, 6pm CST |
| Notion Sync | (silent) | Daily 10pm CST |
| Drift Report | brain-drift | Weekly Sunday 6pm CST |
| Pattern Synthesis | brain-insights | Bi-weekly Wed 2pm CST |
| Project Summary | brain-projects | Weekly Monday 9am CST |
| Resource Digest | brain-resources | Monthly 1st 10am CST |
| Vault + Journal Reindex | (silent) | Daily 5am CST |
| Keyword Expansion | (silent) | Weekly Sunday 2am CST |

All jobs use PTB's `JobQueue` (`run_daily()`, `run_repeating()`). No external scheduler needed.

### Notion Sync Engine

The Notion sync is powered by a Python-native pipeline (`scripts/brain-bot/core/notion_sync.py`) using the `notion-client` SDK.

**Requirements:** `NOTION_TOKEN` environment variable (Notion internal integration token). Run `python scripts/migrate-db.py` once to create the `sync_state` table.

**Architecture:**
- `core/notion_client.py` — Async API wrapper with rate limiting (3 req/sec) and retry
- `core/notion_mappers.py` — Pure transform functions between local and Notion formats
- `core/notion_sync.py` — Sync orchestrator: `NotionSync.run_full_sync()` → `SyncResult`

**Entity flows:** ICOR Tags (push), Action Items (push), Task Status (pull), Projects (pull), Goals (pull), Journal Entries (push, summary-only), Concepts (push), People (pull).

**Hybrid AI:** Optional `ai_client` parameter enables Claude-assisted classification, conflict resolution, and project-goal inference. Falls back to heuristics when unset.

### Bot Architecture

| Module | Description |
|---|---|
| `core/classifier.py` | 4-tier hybrid classification (noise filter → keyword match → embedding similarity → LLM fallback) |
| `core/context_loader.py` | Command-specific SQLite queries + vault file loading + graph traversal + Notion context injection |
| `core/vault_indexer.py` | Vault file scanner, wikilink graph builder, populates `vault_index` table in SQLite |
| `core/journal_indexer.py` | Daily note parser with mood/energy/ICOR detection, populates `journal_entries` table |
| `core/formatter.py` | Telegram HTML message builders for dashboards, reports, sync results, errors |
| `core/message_utils.py` | Message splitting (4096-char limit), HTML-safe send helpers |
| `core/dashboard_builder.py` | ICOR dashboard with heatmaps, attention scores, and quick-action inline buttons |
| `core/search.py` | Hybrid search combining FTS5, vector similarity, and graph traversal |
| `core/embedding_store.py` | sqlite-vec backed vector store for vault file embeddings |
| `core/async_utils.py` | Thread pool executor for offloading sync/CPU-bound work |
| `handlers/feedback.py` | Classification correction handlers + keyword learning loop (updates `keyword_feedback` table) |

### Vault Write-Back Loop

Commands auto-save outputs to the vault so results enrich the knowledge base, not just Telegram. Managed by `_write_command_output_to_vault()` in `handlers/commands.py`:

- **`today`** — Appends "Morning Plan" section to the daily note (`vault/Daily Notes/YYYY-MM-DD.md`)
- **`close`** — Appends "Evening Review" section to the daily note, then re-indexes via `journal_indexer`
- **`schedule`** — Creates a weekly plan file via `create_weekly_plan()`
- **`graduate`** — Saves report + creates individual concept stub files
- **Report commands** (`drift`, `emerge`, `ideas`, `ghost`, `challenge`, `trace`, `connect`) — Auto-saved via `create_report_file()` to `vault/Reports/`. These are defined in the `_AUTO_VAULT_WRITE_COMMANDS` set.
- **`projects`, `resources`** — Not auto-saved; a "Save to Vault" button is added to the message instead.

### Graph Context Loading

The context loader (`core/context_loader.py`) enriches commands with graph-connected vault files via `_GRAPH_CONTEXT_COMMANDS`:

| Command | Graph Strategy | Depth | Behavior |
|---|---|---|---|
| `trace` | `topic` | 2 | Finds files mentioning the user's topic, expands outward |
| `connect` | `intersection` | 1 | Parses two quoted domains, finds overlapping nodes |
| `emerge` | `recent_daily` | 1 | Seeds from recent daily notes, follows links |
| `graduate` | `recent_daily` | 1 | Seeds from recent daily notes, follows links |
| `ideas` | `recent_daily` | 1 | Seeds from recent daily notes, follows links |
| `ghost` | `identity` | 2 | Seeds from ICOR + Values identity files |
| `challenge` | `identity` | 1 | Seeds from ICOR + Values identity files |

Commands in `_NOTION_CONTEXT_COMMANDS` (`today`, `schedule`, `ideas`, `projects`, `close`, `context`, `drift`, `resources`) also receive cached Notion data (projects, goals, dimensions) from `data/notion-registry.json`.

## Known Issues

| Priority | Issue | Status |
|---|---|---|
| P0 | `.env` with live credentials may be in git history | Rotate tokens, add to `.gitignore`, `git rm --cached .env` |
| P1 | Notion push TOCTOU race creates duplicate tasks | Add `push_attempted_at` idempotency column |
| P2 | Prompt files reference MCP tools unavailable in bot context | Create bot-specific prompt versions |

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

## Slack Integration

A Python Slack bot (`scripts/slack-bot/`) provides an asynchronous remote interface to the Second Brain via Socket Mode (no public endpoint).

### Setup
1. Create a Slack app at api.slack.com with Socket Mode enabled
2. Copy `.env.example` to `.env` and fill in tokens
3. Run `scripts/setup-slack.sh` to create channels
4. Run `python scripts/migrate-db.py` to prepare sync tables
5. Start: `cd scripts/slack-bot && pip install -r requirements.txt && python app.py`
6. Auto-start: `cp scripts/slack-bot/launchd/com.brain.slack-bot.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.brain.slack-bot.plist`

### Slack Channel Architecture

| Channel | Purpose |
|---|---|
| `#brain-inbox` | Drop thoughts here — bot routes to ICOR dimension channels |
| `#brain-daily` | Morning briefings (7am) and evening reviews (9pm) |
| `#brain-actions` | Action items with Complete/Snooze/Delegate buttons |
| `#brain-dashboard` | ICOR heatmap, attention scores, project status (6am/6pm) |
| `#brain-ideas` | Idea generation reports |
| `#brain-drift` | Alignment drift reports (weekly Sunday 6pm) |
| `#brain-insights` | Pattern synthesis, ghost reflections, trace timelines |
| `#brain-health` | Health & Vitality captures |
| `#brain-wealth` | Wealth & Finance captures |
| `#brain-relations` | Relationships captures |
| `#brain-growth` | Mind & Growth captures |
| `#brain-purpose` | Purpose & Impact captures |
| `#brain-systems` | Systems & Environment captures |
| `#brain-projects` | Active projects, weekly summaries (Mon 9am), cross-posted captures |
| `#brain-resources` | Resource catalog, monthly digests (1st 10am), cross-posted captures |

### Slack Slash Commands

| Slack Command | Maps To | Output Channel |
|---|---|---|
| `/brain-today` | `/brain:today` | #brain-daily |
| `/brain-close` | `/brain:close-day` | #brain-daily |
| `/brain-drift` | `/brain:drift` | #brain-drift |
| `/brain-emerge` | `/brain:emerge` | #brain-insights |
| `/brain-ideas` | `/brain:ideas` | #brain-ideas |
| `/brain-schedule` | `/brain:schedule` | #brain-daily |
| `/brain-ghost` | `/brain:ghost` | #brain-insights |
| `/brain-status` | Quick SQLite query | #brain-dashboard |
| `/brain-sync` | `/brain:sync-notion` | DM |
| `/brain-projects` | `/brain:projects` | #brain-projects |
| `/brain-resources` | `/brain:resources` | #brain-resources |
| `/brain-trace` | `/brain:trace` | #brain-insights |
| `/brain-connect` | `/brain:connect` | #brain-insights |
| `/brain-challenge` | `/brain:challenge` | #brain-insights |
| `/brain-graduate` | `/brain:graduate` | #brain-insights |
| `/brain-context` | `/brain:context-load` | DM |

### Scheduled Automations

| Job | Channel | Schedule |
|---|---|---|
| Morning Briefing | #brain-daily | Daily 7am |
| Evening Prompt | #brain-daily | Daily 9pm |
| Dashboard Refresh | #brain-dashboard | Daily 6am, 6pm |
| Notion Sync | (silent) | Daily 10pm |
| Drift Report | #brain-drift | Weekly Sunday 6pm |
| Pattern Synthesis | #brain-insights | Bi-weekly Wed 2pm |
| Project Summary | #brain-projects | Weekly Monday 9am |
| Resource Digest | #brain-resources | Monthly 1st 10am |
| Vault + Journal Reindex | (silent) | Daily 5am |
| Keyword Expansion | (silent) | Weekly Sunday 2am |

### Notion Sync Engine

The Notion sync is powered by a Python-native pipeline (`scripts/slack-bot/core/notion_sync.py`) using the `notion-client` SDK. This replaces the previous Claude API approach which lacked MCP tool access.

**Requirements:** `NOTION_TOKEN` environment variable (Notion internal integration token). Run `python scripts/migrate-db.py` once to create the `sync_state` table.

**Architecture:**
- `core/notion_client.py` — Async API wrapper with rate limiting (3 req/sec) and retry
- `core/notion_mappers.py` — Pure transform functions between local and Notion formats
- `core/notion_sync.py` — Sync orchestrator: `NotionSync.run_full_sync()` → `SyncResult`

**Entity flows:** ICOR Tags (push), Action Items (push), Task Status (pull), Projects (pull), Goals (pull), Journal Entries (push, summary-only), Concepts (push), People (pull).

**Hybrid AI:** Optional `ai_client` parameter enables Claude-assisted classification, conflict resolution, and project-goal inference. Falls back to heuristics when unset.

### Slack Bot Architecture

| Module | Description |
|---|---|
| `core/classifier.py` | 4-tier hybrid classification (noise filter → keyword match → embedding similarity → LLM fallback) |
| `core/context_loader.py` | Command-specific SQLite queries + vault file loading + graph traversal + Notion context injection |
| `core/vault_indexer.py` | Vault file scanner, wikilink graph builder, populates `vault_index` table in SQLite |
| `core/journal_indexer.py` | Daily note parser with mood/energy/ICOR detection, populates `journal_entries` table |
| `core/formatter.py` | Slack Block Kit message builders for dashboards, reports, sync results, errors |
| `handlers/feedback.py` | Classification correction handlers + keyword learning loop (updates `keyword_feedback` table) |

### Vault Write-Back Loop

Commands auto-save outputs to the vault so results enrich the knowledge base, not just Slack. Managed by `_write_command_output_to_vault()` in `handlers/commands.py`:

- **`today`** — Appends "Morning Plan" section to the daily note (`vault/Daily Notes/YYYY-MM-DD.md`)
- **`close-day`** — Appends "Evening Review" section to the daily note, then re-indexes via `journal_indexer`
- **`schedule`** — Creates a weekly plan file via `create_weekly_plan()`
- **`graduate`** — Saves report + creates individual concept stub files
- **Report commands** (`drift`, `emerge`, `ideas`, `ghost`, `challenge`, `trace`, `connect`) — Auto-saved via `create_report_file()` to `vault/Reports/`. These are defined in the `_AUTO_VAULT_WRITE_COMMANDS` set.
- **`projects`, `resources`** — Not auto-saved; a "Save to Vault" button is added to the Slack message instead.

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

Commands in `_NOTION_CONTEXT_COMMANDS` (`today`, `schedule`, `ideas`, `projects`, `close-day`, `context-load`, `drift`, `resources`) also receive cached Notion data (projects, goals, dimensions) from `data/notion-registry.json`.

## Known Issues (from 8-perspective audit, 2026-03-03)

See `AUDIT-REPORT.md` for full details. Critical items:

| Priority | Issue | Fix |
|---|---|---|
| P0 | `.env` with live credentials may be in git history | Rotate tokens, add to `.gitignore`, `git rm --cached .env` |
| P0 | SQLite has no WAL mode — DB locks under thread contention | Add `PRAGMA journal_mode=WAL` at startup |
| P0 | Vault reindex wipes table without transaction | Wrap DELETE+INSERT in BEGIN...COMMIT |
| P1 | Unbounded thread spawning per Slack event | Replace with `ThreadPoolExecutor(max_workers=8)` |
| P1 | No prompt caching — 60-80% API cost savings available | Add `cache_control: {"type": "ephemeral"}` to system prompt |
| P1 | Tier 3 classifier uses Sonnet instead of Haiku | Route to `claude-haiku-4-5` for 95% cost reduction |
| P1 | Notion push TOCTOU race creates duplicate tasks | Add `push_attempted_at` idempotency column |
| P1 | No progress feedback after slash command ack | Add `chat_postEphemeral` "result ready" notification |
| P2 | Zero automated tests | Add pytest suite for classifier, vault_ops, journal_indexer |
| P2 | Prompt files reference MCP tools unavailable in Slack context | Create Slack-specific prompt versions |
| P2 | No `/brain-help` command for 14 slash commands | Register help command with command table |
| P2 | No `/brain:find` semantic search command | Highest-value missing feature |

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

## SQLite Database

The local SQLite database at `data/brain.db` indexes vault content for fast querying. Use `sqlite3 data/brain.db` to query. Key tables: journal_entries, action_items, concept_metadata, icor_hierarchy, attention_indicators, vault_sync_log.

## Slack Integration

A Python Slack bot (`scripts/slack-bot/`) provides an asynchronous remote interface to the Second Brain via Socket Mode (no public endpoint).

### Setup
1. Create a Slack app at api.slack.com with Socket Mode enabled
2. Copy `.env.example` to `.env` and fill in tokens
3. Run `scripts/setup-slack.sh` to create channels
4. Start: `cd scripts/slack-bot && pip install -r requirements.txt && python app.py`
5. Auto-start: `cp scripts/slack-bot/launchd/com.brain.slack-bot.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.brain.slack-bot.plist`

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

### Scheduled Automations

| Job | Channel | Schedule |
|---|---|---|
| Morning Briefing | #brain-daily | Daily 7am |
| Evening Prompt | #brain-daily | Daily 9pm |
| Dashboard Refresh | #brain-dashboard | Daily 6am, 6pm |
| Notion Sync | (silent) | Daily 10pm |
| Drift Report | #brain-drift | Weekly Sunday 6pm |
| Pattern Synthesis | #brain-insights | Bi-weekly Wed 2pm |

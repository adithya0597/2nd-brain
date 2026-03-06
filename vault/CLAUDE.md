# vault/ — Obsidian Vault

## Purpose

The Obsidian vault is the knowledge base for the Second Brain. Contains daily journals, concepts, meeting notes, projects, identity files, and bot-generated reports. The Slack bot reads from and writes to this directory.

## Directory Structure

| Directory | Contents | Bot Access |
|---|---|---|
| `Identity/` | ICOR.md, Values.md, Active-Projects.md — source-of-truth identity files | Read (context loading) |
| `Daily Notes/` | `YYYY-MM-DD.md` — daily journals with frontmatter | Read + Write (captures, morning/evening reviews) |
| `Concepts/` | `Concept-Name.md` — evergreen concept notes | Read + Write (graduate command) |
| `Dimensions/` | One `.md` per ICOR dimension — wikilink targets for graph connectivity | Write (created by bot on startup) |
| `Inbox/` | `YYYY-MM-DD-HHMMSS-source.md` — raw captures from Slack | Write only |
| `Reports/` | `YYYY-MM-DD-command.md` — auto-saved command outputs | Write only |
| `Meetings/` | `YYYY-MM-DD-Meeting-Topic.md` — meeting notes | Read (process-meeting command) |
| `Projects/` | `Project-Name.md` — project documentation | Read (context loading) |
| `Templates/` | Daily Note.md, Concept.md, Meeting.md, Project.md | Read (file creation templates) |
| `Archive/` | Moved/archived content | Not accessed |
| `.obsidian/` | Obsidian app settings | Not accessed |

## Frontmatter Conventions

All markdown files use YAML frontmatter between `---` delimiters:

```yaml
# Daily notes
type: journal
date: "YYYY-MM-DD"
mood: great | good | okay | low | bad
energy: high | medium | low
icor_elements: ["Element Name", ...]

# Concepts
type: concept
status: seedling | growing | evergreen

# Dimensions (bot-generated)
type: dimension
icor_level: dimension
title: "Health & Vitality"

# Inbox captures (bot-generated)
type: inbox
date: YYYY-MM-DD
source: slack
status: unprocessed
```

## Linking Conventions

- `[[wikilinks]]` for internal vault connections (tracked by `vault_indexer`)
- `[[Dimension-Name]]` in daily notes for ICOR routing visibility
- The vault indexer extracts both outgoing and incoming links to build a bidirectional graph in `vault_index`

## Daily Note Sections

Template sections (from `Templates/Daily Note.md`):
1. `## Morning Intentions` — filled by `/brain:today`
2. `## Log` — capture entries appended here by the bot
3. `## Reflections` — manual user content
4. `## Actions` — checkbox task items

Bot appends:
- `## Morning Plan` — from `/brain:today` command
- `## Evening Review` — from `/brain:close-day` command
- Slack captures as `**[Slack Capture]** text _(routed to Dimension)_` under `## Log`

## Bot Modifications

The Slack bot writes to the vault in these ways:

| Operation | Target | Trigger |
|---|---|---|
| Create daily note | `Daily Notes/YYYY-MM-DD.md` | Any capture or morning command if note doesn't exist |
| Append capture to daily note | `## Log` section | Every `#brain-inbox` message |
| Create inbox entry | `Inbox/YYYY-MM-DD-HHMMSS-slack.md` | Every classified capture |
| Append morning plan | `## Morning Plan` section | `/brain:today` |
| Append evening review | `## Evening Review` section | `/brain:close-day` |
| Create report file | `Reports/YYYY-MM-DD-command.md` | drift, emerge, ideas, ghost, challenge, trace, connect, graduate |
| Create weekly plan | `Reports/` or `Projects/` | `/brain:schedule` |
| Create concept stubs | `Concepts/Concept-Name.md` | `/brain:graduate` |
| Ensure dimension pages | `Dimensions/Dimension-Name.md` | Bot startup (once) |

## Gotchas

- **Dimension pages are bot-created**: The 6 dimension page files in `Dimensions/` are created by `ensure_dimension_pages()` in `vault_ops.py` on bot startup. They serve as wikilink targets for graph connectivity.
- **Inbox files accumulate**: Each Slack capture creates a new file in `Inbox/`. These are never auto-cleaned. Periodically review and archive.
- **Daily note template uses Obsidian syntax**: `{{date:YYYY-MM-DD}}` is an Obsidian Templater token, not processed by the bot. The bot creates daily notes with actual dates.
- **Bot appends are additive**: The bot never overwrites daily note content — it appends to specific sections. Multiple morning plans or captures in the same day are all preserved.
- **Vault indexer scans all `.md` files**: Including `.obsidian/` files. The indexer filters by extension only. Hidden/config files with `.md` extension will be indexed.

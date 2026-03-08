# .claude/commands/brain/ — Command Prompt Files

## Purpose

18+ markdown prompt files that define the instructions for each `/brain:*` command. These are loaded as the system prompt suffix when the Telegram bot (or Claude Code directly) executes a command.

## How Prompts Are Loaded

1. User invokes a command (e.g., `/today` in Telegram or `/brain:today` in Claude Code)
2. `context_loader.py:load_command_prompt(command_name)` reads `.claude/commands/brain/{command_name}.md`
3. `context_loader.py:load_system_context()` reads the root `CLAUDE.md` as the base system prompt
4. The full system prompt is: `{CLAUDE.md}\n\n---\n\n{command_prompt.md}`
5. `gather_command_context()` assembles context data (SQL results, vault files, graph files, Notion data)
6. `build_claude_messages()` combines everything into an Anthropic API messages array

## Prompt Files

| File | Command | Description | Context Sources |
|---|---|---|---|
| `context-load.md` | `/brain:context-load` | Pre-load session context | SQL + vault identity files + Notion |
| `today.md` | `/brain:today` | Morning briefing + daily note creation | SQL + vault + Notion projects |
| `close-day.md` | `/brain:close-day` | Evening review + action extraction | SQL + Notion |
| `drift.md` | `/brain:drift` | 60-day alignment analysis | SQL + vault ICOR + Notion |
| `graduate.md` | `/brain:graduate` | Promote journal themes to concepts | SQL + graph (recent_daily) |
| `trace.md` | `/brain:trace` | Concept evolution timeline | SQL + graph (topic) |
| `emerge.md` | `/brain:emerge` | Surface unnamed patterns | SQL + graph (recent_daily) |
| `ideas.md` | `/brain:ideas` | Actionable idea generation (5 categories) | SQL + graph (recent_daily) + Notion |
| `schedule.md` | `/brain:schedule` | Energy-aware weekly planning | SQL + vault + Notion |
| `ghost.md` | `/brain:ghost` | Digital twin responses | vault identity + graph (identity) |
| `challenge.md` | `/brain:challenge` | Red-team beliefs with counter-evidence | vault identity + graph (identity) + SQL |
| `connect.md` | `/brain:connect` | Serendipitous cross-domain connections | SQL + graph (intersection) |
| `projects.md` | `/brain:projects` | Active project dashboard | SQL + vault + Notion |
| `resources.md` | `/brain:resources` | Knowledge base catalog | SQL + Notion |
| `process-inbox.md` | `/brain:process-inbox` | Route inbox captures | SQL |
| `process-meeting.md` | `/brain:process-meeting` | Parse meeting transcript, extract actions | SQL |
| `refresh-dashboard.md` | `/brain:refresh-dashboard` | Recalculate attention scores | SQL |
| `sync-notion.md` | `/brain:sync-notion` | Bidirectional Notion sync instructions | SQL + Notion |
| `find.md` | `/brain:find` | Semantic vault search | SQL + FTS5 + vector |
| `engage.md` | `/brain:engage` | Engagement analysis | SQL + vault |

## Prompt Structure Pattern

Most prompts follow this structure:
1. **Title + one-line description**
2. **Steps** — numbered instructions with embedded SQL queries
3. **Format** — expected output format (usually markdown)
4. **Rules/constraints** — guardrails for the AI

## Context Data Available at Runtime

The prompt file itself contains the "ideal" instructions (including SQL queries and Notion tool references). At runtime, the context loader pre-gathers all data and injects it as a `## Context Data` section in the user message. The prompt references this data.

Context sources by command are defined in `context_loader.py`:
- `_COMMAND_QUERIES` — SQL queries per command (pre-executed, results injected)
- `_COMMAND_VAULT_FILES` — identity files per command (read and injected)
- `_GRAPH_CONTEXT_COMMANDS` — graph traversal strategies (files discovered and injected)
- `_NOTION_CONTEXT_COMMANDS` — Notion registry data (cached JSON injected)

## Gotchas

- **Prompts reference Notion MCP tools**: Several prompts (today, ideas, schedule, projects) instruct Claude to "Use Notion MCP tools." This works in Claude Code sessions but **not** in the Telegram bot path, which uses the Anthropic API without MCP. The context loader pre-gathers Notion data as a workaround.
- **SQL in prompts is documentation**: The SQL queries embedded in prompt files describe the *intent*. The actual executed queries live in `context_loader.py:_COMMAND_QUERIES` and may differ.
- **Prompt filenames must match command names**: `load_command_prompt()` resolves `{command_name}.md`. A filename mismatch causes a `FileNotFoundError`.
- **No prompt variables**: Prompts are static markdown. User input and context data are injected via the messages array, not via template substitution in the prompt.
- **Token budget**: Each prompt is 1-8 KB. Combined with CLAUDE.md (~5 KB) and context data, total input can reach 20-50K tokens per command.

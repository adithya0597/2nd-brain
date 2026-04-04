---
type: report
command: research
date: 2026-04-03
status: active
tags: [architecture, claude-connectors, task-management, analysis]
---

# The "Second Brain Stack" — Analysis & Implementation Plan

## What Is It?

A workflow pattern circulating in the Claude community that chains three primitives:

1. **Claude Project** (claude.ai) — per-project workspace with custom instructions + persistent memory
2. **Connectors** — remote MCP servers linking Claude to task managers (Todoist, Linear, Asana, etc.)
3. **`/next-task` Skill** — a reusable prompt that bridges the two:

```
Find my project in [task manager].
Pull all open tasks.
Check this project's memory.
What is the single highest-priority task right now?
Start working on it.
```

The pitch: Claude project holds the "why" and context, the task manager holds the "what", and the skill autonomously picks and executes the next thing.

## How It Maps to What We Already Have

| Capability | "Stack" Pattern | Our 2nd-Brain System | Gap? |
|---|---|---|---|
| Project memory | Claude Project memory (auto, opaque) | CLAUDE.md + claude-mem + SQLite + vault index + embeddings | We're deeper. No gap. |
| Task management | External via Connector (Todoist/Linear) | Notion Tasks DB + action_items table + intent extractor | Partial gap — see below |
| Knowledge base | File uploads (30MB/file, RAG) | Obsidian vault + section chunking + 4-channel hybrid search | We're deeper. No gap. |
| Classification | None (manual routing) | 5-tier classifier + ICOR dimensions | They don't have this |
| Automation | Manual ("ask for next task") | PTB JobQueue (morning briefings, dashboard, drift, sync) | We're deeper — push model |
| `/next-task` pull | The core skill | **We don't have this** | **Real gap** |
| Graph intelligence | None | vault_nodes + vault_edges + Louvain + BFS + ICOR affinity | They don't have this |
| Interface | claude.ai web chat | Telegram bot + Obsidian + CLI | Different, not worse |

## The One Thing Worth Stealing

**The `/next-task` autonomous execution loop.** Everything else we already have (and more). But we lack a single command that:

1. Checks active tasks (from Notion or action_items)
2. Prioritizes based on due date, energy level, ICOR dimension balance
3. Loads relevant context for that task
4. Starts executing it

This is the "assistant that acts" vs "filing cabinet that stores" distinction the grill report identified as our core problem.

## What Connectors Are (Technically)

Connectors are **remote MCP servers** curated by Anthropic, available on claude.ai, Claude Desktop, and the API. They launched July 2025 with 50+ integrations.

- Same MCP protocol used by Claude Code's local MCP servers
- Support both read (pull tasks) and write (create/update tasks)
- Some support "Interactive Apps" — UI rendered inside chat (Asana, Figma, Slack)
- Available on free plans; custom connectors require paid

**Key insight for us:** The same MCP servers powering Connectors can be configured in Claude Code directly. We don't need claude.ai — we can wire the same task management MCP servers into our CLI setup.

## Implementation Options

### Option A: Notion MCP (Already Available)

We already have the Notion MCP server configured (`mcp__claude_ai_Notion__*` tools). Our Notion workspace has Tasks, Projects, and Goals databases. We could build `/next-task` today using existing infrastructure:

```
/next-task flow:
1. Query Notion Tasks DB (Status = "To Do" or "Doing", sorted by Due date)
2. Query action_items table (status = "pending", sorted by due_date)
3. Load ICOR dimension signals (which dimensions are cold/frozen?)
4. Cross-reference: prioritize tasks in neglected dimensions
5. Load relevant vault context for the top task
6. Present task + context + suggest next action
```

**Pros:** Zero new dependencies. Uses existing Notion sync + ICOR signals.
**Cons:** Notion API is slower (~1-3s per query). No real-time task state.

### Option B: Add a Dedicated Task Manager MCP

Add a Todoist or Linear MCP server alongside Notion for faster task operations:

- **Todoist MCP** (`greirson/mcp-todoist`): Natural language task management, bulk operations, labels/priorities
- **Linear MCP** (`jerhadf/linear-mcp-server`): Issues, projects, teams, cycles — more engineering-oriented

**Pros:** Faster queries, native priority/label support, designed for task management.
**Cons:** Another system to sync. Notion already has tasks. Adds complexity.

### Option C: Build on action_items Table (Local-First)

Skip external task managers entirely. The `action_items` table + intent extractor already captures tasks with due dates and priorities. Build `/next-task` purely against local SQLite:

```sql
SELECT description, due_date, priority, icor_element
FROM action_items
WHERE status = 'pending'
ORDER BY
  CASE WHEN due_date <= date('now') THEN 0 ELSE 1 END,
  CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
  due_date ASC
LIMIT 1;
```

**Pros:** Instant (local SQLite), no API calls, no new dependencies, works offline.
**Cons:** Limited to what the bot captured. Doesn't include manually-created Notion tasks.

## Recommended Approach: Option A + C Hybrid

Use **local action_items as primary** (fast, always available) with **Notion as enrichment** (pull fresh tasks on demand):

### New Skill: `/brain:next-task`

```markdown
# /brain:next-task — Autonomous Task Execution

1. Query pending action_items (local, instant)
2. Query Notion Tasks DB via MCP (Status = "To Do", Due <= this week)
3. Merge and deduplicate by description similarity
4. Score each task:
   - Overdue: +10 points
   - Due today: +5 points
   - High priority: +3 points
   - In a frozen/cold ICOR dimension: +2 points (balance incentive)
   - Has project context in vault: +1 point
5. Pick the top task
6. Load relevant vault files, project context, and recent captures
7. Present: "Your next task is: [X]. Here's what you need to know: [context]"
8. If user confirms: start working on it (open relevant files, draft responses, etc.)
```

### New Skill: `/brain:work-queue`

Shows the prioritized task queue without executing:

```
📋 Work Queue (5 tasks)

1. 🔴 Call dentist (OVERDUE, Health & Vitality, due Mar 31)
2. 🟡 Set up demo environment (due today, Mind & Growth)
3. 🟡 Review pitch deck with Sarah (due tomorrow, Purpose & Impact)
4. ⚪ Update LinkedIn profile (no due date, Wealth & Finance)
5. ⚪ Read chapter 4 of DDIA (no due date, Mind & Growth)

Run /next-task to start #1, or reply with a number to pick a different task.
```

## What This Adds to the Current Claude Setup

| Current State | With This Addition |
|---|---|
| Captures filed to dimensions | Captures become actionable tasks with due dates (already have intent extractor) |
| Morning briefing lists what happened | Morning briefing recommends what to do next |
| Dashboard shows brain level | Dashboard shows work queue with priority scores |
| User asks "what should I do?" | System pushes "here's your next task + context" |
| 17 captures, 0 completed actions | Clear path from capture → task → execution → completion |

## Estimated Effort

| Component | Lines | Time |
|---|---|---|
| `.claude/commands/brain/next-task.md` (prompt file) | ~40 | 30min |
| `core/task_scorer.py` (priority scoring logic) | ~80 | 1hr |
| `core/context_loader.py` (add task context gathering) | ~30 | 30min |
| `handlers/commands.py` (wire up /next-task) | ~20 | 15min |
| `core/formatter.py` (work queue formatting) | ~30 | 30min |
| **Total** | **~200** | **~3hr** |

No new tables, no new dependencies, no external task manager needed. Uses existing action_items + Notion MCP + ICOR dimension signals.

## What NOT to Build

- Don't add Todoist/Linear — Notion already has tasks, adding another system creates sync headaches
- Don't auto-execute tasks without user confirmation — the skill should present + recommend, not act unilaterally
- Don't replicate Claude Projects — our CLAUDE.md + claude-mem + vault is already more powerful
- Don't add "Connectors" concept — MCP servers already serve this role in Claude Code

## Conclusion

The "Second Brain Stack" pattern is a **simplified, no-code version of what we already have**, minus the graph intelligence, classification pipeline, and proactive automation. The one valuable idea is the **`/next-task` autonomous execution pattern** — bridging task awareness with context-rich execution.

We can implement this in ~200 lines using existing infrastructure (action_items + Notion MCP + ICOR signals + vault context), closing the gap between "capture" and "action" that the grill report identified as the system's core weakness.

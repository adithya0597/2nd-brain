---
type: report
command: grill
date: 2026-04-02
status: active
tags: [adversarial-review, quality-gate]
target: tasks/capture-pipeline-fix-proposal.md
---

# Grill Report: Fix the Capture Pipeline (Debug + Enhance)

**Target**: `tasks/capture-pipeline-fix-proposal.md`
**Date**: 2026-04-02
**Griller team**: 7 independent adversarial agents (zero shared context)
**Prior grills**: Bulk import REJECTED 2.5/10, Unified pipeline 3.3/10

## Executive Summary

This third proposal correctly identifies the root cause: a gate condition at `capture.py:293` that discards non-task extraction results. That diagnosis alone represents a significant improvement over prior attempts. However, six of seven agents flagged the same critical blind spot -- the outer `is_actionable` guard at line 279, which uses a narrow regex (`_ACTION_PATTERNS`) that prevents many natural-language captures from ever reaching extraction. The proposal fixes the second gate while ignoring the first. The 4-line gate fix is sound but understated (closer to 15-25 lines once the task-specific confirmation UI is adapted for non-task intents). Decisions 2-5 received mixed reviews: command prefixes risk bifurcating the capture pipeline, vault routing is underscoped, measurement is too thin to be called empirical, and the scope constraint is wise but reverse-engineered from prior grill feedback. The Bias Detector identified Goodhart's Law as the systemic issue: this proposal optimizes for grill scores rather than for the user's actual needs. The composite score of 5.4/10 clears the prior attempts but falls short of a clean approval.

## Challenged Decisions

| # | Decision | Avg Score | Weakest Lens | Key Challenge |
|---|---|---|---|---|
| 1 | Fix gate condition (~4 lines) | 6.2 | Risk (4/10) | Outer `is_actionable` guard at L279 is the real first gate; task-specific UI flows to non-task intents; confirm handler creates Notion tasks for ideas |
| 2 | Hybrid UX with command prefixes | 4.7 | User Impact (3/10) | Bypasses classifier/provenance/engagement pipeline; analytics go blind; `/idea` vs `/ideas` collision; adds friction for 2-5 captures/day |
| 3 | Route non-task intents to vault | 4.8 | User Impact (2/10) | Target dirs don't exist; "update -> project" is underscoped/dangerous; "reflection -> daily note" is already default behavior; doesn't solve stated pain |
| 4 | Extraction quality measurement | 4.3 | Bias (3/10) | N=10 is anecdote not statistics; hand-picked test set measures success on designed inputs; no scoring rubric or LLM variance control |
| 5 | Scope boundary (NO rebuild) | 7.4 | Bias (4/10) | Strongest decision but reverse-engineered from prior grill feedback; hides `is_actionable` as a known limitation |

## Per-Lens Critiques

### Devil's Advocate (avg 5.0/10)

The Devil's Advocate verified the codebase end-to-end and found that the proposal's "4 lines" framing anchors the reader on triviality. The actual complexity is in the downstream confirmation UI: buttons say "Create Task / Edit / Skip" for all intents, meaning a reflection would show a "Create Task" button. The `handle_extraction_confirm` callback at line 519 calls `insert_action_item()` unconditionally -- ideas confirmed by the user become Notion Tasks. The agent also found that `reflection -> daily note` routing is already the default behavior (line 233), making that routing path a no-op. The measurement plan (N=10) was rated 3/10 as it has no statistical power across 6 intent types.

| Decision | Defensibility |
|---|---|
| 1. Fix gate | 6/10 |
| 2. Command prefixes | 5/10 |
| 3. Non-task routing | 4/10 |
| 4. Measurement | 3/10 |
| 5. Scope boundary | 7/10 |

### Feasibility Audit (avg 8.6/10)

The most optimistic lens. Confirmed the bug is real and the fix is small, but adjusted estimates upward: Decision 1 needs 1-2 hours (not 10-30 min) to handle non-task UX properly. Decision 2 is clean at 2-4 hours. Decision 3's "update -> project" route is the underscoped item -- no `append_to_project()` function exists, and the simpler alternative (all non-task intents to `vault/Inbox/` with intent frontmatter tags) drops complexity dramatically. Overall timeline of 1-2 days was assessed as realistic at the upper bound. Top risk: the `is_actionable` gate at line 279 means extraction only runs when the classifier detects action patterns.

| Decision | Feasibility |
|---|---|
| 1. Fix gate | 8/10 |
| 2. Command prefixes | 9/10 |
| 3. Non-task routing | 6/10 (9/10 with simpler alternative) |
| 4. Measurement | 10/10 |
| 5. Scope boundary | 10/10 |

### Bias Detection (avg 4.4/10)

Identified the systemic meta-bias: **Goodhart's Law**. The proposal was explicitly reverse-engineered from prior grill scoring criteria. Each decision maps to a specific prior critique: the "Reasons NOT to Do This" section was added because the second grill penalized its absence; command prefixes came from the Alt Paths agent's suggestion; the scope constraints match the second grill's recommendations verbatim. The "95% functional" claim was challenged -- 19 captures over the system's lifetime could indicate the pipeline barely works. The strongest criticism: "Decision 1 is the fix. Ship it in 30 minutes. Observe for a week. Then decide if Decisions 2-3 are needed. That version would score poorly on the grill but would be the correct engineering response."

| Decision | Objectivity |
|---|---|
| 1. Fix gate | 5/10 |
| 2. Command prefixes | 4/10 |
| 3. Non-task routing | 6/10 |
| 4. Measurement | 3/10 |
| 5. Scope boundary | 4/10 |

### Cost-Benefit Challenge (avg 7.2/10)

Rated Decision 1 as 10/10 value -- the single highest-leverage change, recovering value already being paid for (LLM extraction tokens). Recommended shipping it immediately as a standalone fix. Decision 2 (command prefixes) rated 4/10 -- marginal benefit since the LLM handles intent detection in 300ms, and the user can correct via "Skip" button. Decision 5 (scope constraint) rated 9/10 as the most important meta-decision preventing scope creep. Flagged that `handle_extraction_confirm` creates Notion tasks unconditionally, making the "4-line fix" actually 15-20 lines. Recommended deferring Decisions 2-3 until post-fix usage data confirms they are needed.

| Decision | Value-for-Effort |
|---|---|
| 1. Fix gate | 10/10 |
| 2. Command prefixes | 4/10 |
| 3. Non-task routing | 6/10 |
| 4. Measurement | 7/10 |
| 5. Scope boundary | 9/10 |

### Alternative Paths (avg 7.8/10 across alternatives)

Rather than scoring the 5 proposal decisions directly, this agent generated 5 alternative approaches ranked by exploration breadth. The top recommendation: **Universal Extraction** (remove both the `is_actionable` gate and the `intent == "task"` gate, show intent-appropriate buttons). This fixes the root cause with minimal code and makes every future intent type work automatically, rendering the command prefixes unnecessary. Other alternatives explored: Telegram message entities as a lightweight DSL (8/10), event-sourced capture with batch triage (9/10), observability-first with a `capture_trace` table (6/10), and a conversational agent that asks one clarifying question when ambiguous (9/10). The agent's core insight: the prefix commands are premature optimization of a pipeline you cannot yet observe.

| Alternative | Exploration Breadth |
|---|---|
| 1. Universal extraction (remove gate) | 7/10 |
| 2. Telegram entities as DSL | 8/10 |
| 3. Event-sourced + batch triage | 9/10 |
| 4. Observability first (capture_trace) | 6/10 |
| 5. Conversational agent | 9/10 |

### Risk Amplification (avg 5.0/10)

The most technically detailed critique. Identified three high-severity risks the proposal does not address: (1) The `is_actionable` outer guard at line 279 means the 4-line fix is inert for non-actionable captures -- the proposal fixes the second gate while the first gate still blocks. (2) Command prefixes bypass the entire classification/provenance/engagement pipeline, making engagement metrics, brain level, dimension signals, and drift reports go blind. (3) `handle_extraction_confirm` calls `_create_notion_task_immediate` unconditionally -- ideas confirmed by users become Notion Tasks, polluting the task database. Also flagged that `_pending_extractions` is an in-memory dict lost on bot restart, and broadening the gate increases lost extractions.

| Decision | Risk Awareness |
|---|---|
| 1. Fix gate | 4/10 |
| 2. Command prefixes | 3/10 |
| 3. Non-task routing | 5/10 |
| 4. Measurement | 6/10 |
| 5. Scope boundary | 7/10 |

### User Impact Assessment (avg 2.8/10)

The harshest lens. Argued that the user's stated pain point ("no deadline, no person, no reminder") is 90% solved by Decision 1 alone. Decision 2 (command prefixes) rated 3/10 -- for a single user sending 2-5 messages/day, the cost of learning 3 new commands exceeds the benefit, especially since the user can rephrase captures to trigger the existing actionability regex. Decision 3 (vault routing) rated 2/10 -- the user complained about lost extraction data, not about vault folder structure; this solves a problem that was not stated. Decision 4 rated 0/10 for direct user visibility. Identified two ignored problems with higher user impact than Decisions 2-3: the narrow `_check_actionable` regex (misses "dentist Thursday"), and the reminder window only fires for tasks due today or tomorrow ("by Friday" on Wednesday creates no reminder).

| Decision | User Impact |
|---|---|
| 1. Fix gate | 5/10 |
| 2. Command prefixes | 3/10 |
| 3. Non-task routing | 2/10 |
| 4. Measurement | 0/10 |
| 5. Scope boundary | N/A |

## Blind Spots Exposed

1. **The `is_actionable` outer guard (line 279)** -- Flagged by 6 of 7 agents. The `_ACTION_PATTERNS` regex only matches explicit action verbs ("need to", "should", "call", "email"). Captures like "dentist appointment Thursday" or "I had an idea about X" never reach extraction at all. Fixing line 293 without addressing line 279 leaves an entire class of captures stranded. The proposal does not mention this gate.

2. **`handle_extraction_confirm` creates Notion tasks unconditionally** -- Flagged by Devil's Advocate, Cost-Benefit, and Risk Amplifier. If non-task intents reach the confirmation UI, pressing "Create Task" inserts an idea or reflection into the Notion Tasks DB with Status "To Do". The confirm handler needs intent-aware branching. This pushes the "4 lines" to 15-25 lines.

3. **Reminder window is too narrow** -- Flagged only by User Impact. `reminder_manager` only fires for tasks due today or tomorrow. "Call Sarah by Friday" sent on Wednesday creates no reminder. The proposal lists "no reminder" as a pain point but the fix does not address the reminder scheduling window.

4. **Command prefixes blind the intelligence layer** -- Flagged by Risk Amplifier and Devil's Advocate. Prefix-routed captures skip `captures_log`, `classifications`, daily note append, and dimension routing. Engagement metrics, brain level, dimension signals, and drift reports lose visibility. The provenance gap compounds over time.

5. **`_pending_extractions` in-memory dict** -- Flagged only by Risk Amplifier. This dict is lost on bot restart. Broadening the gate stores more extractions in memory, increasing the window for data loss between confirmation message and user tap.

## Confidence Scores

| Decision | Devil | Feasibility | Bias | Cost-Benefit | Alt Paths | Risk | User Impact | **Average** |
|---|---|---|---|---|---|---|---|---|
| 1. Fix gate | 6 | 8 | 5 | 10 | -- | 4 | 5 | **6.3** |
| 2. Command prefixes | 5 | 9 | 4 | 4 | -- | 3 | 3 | **4.7** |
| 3. Non-task routing | 4 | 6 | 6 | 6 | -- | 5 | 2 | **4.8** |
| 4. Measurement | 3 | 10 | 3 | 7 | -- | 6 | 0 | **4.8** |
| 5. Scope boundary | 7 | 10 | 4 | 9 | -- | 7 | -- | **7.4** |
| **Agent Average** | **5.0** | **8.6** | **4.4** | **7.2** | **7.8*** | **5.0** | **2.5** | **5.4** |

*Alt Paths scored 5 alternative approaches (7-9/10 exploration breadth) rather than the 5 proposal decisions. Their recommendation: universal extraction (remove both gates) supersedes the proposal's approach.

## Comparison: Previous vs Current

| Metric | Unified Pipeline (v2) | Capture Fix (v3) | Delta |
|---|---|---|---|
| Composite Score | 3.3/10 | 5.4/10 | +2.1 |
| Root Cause Identified | No (speculative) | Yes (verified at line 293) | Major improvement |
| Code Audit Performed | No | Yes (all agents read codebase) | Major improvement |
| Scope Discipline | None (full pipeline rebuild) | Strong (NO constraints) | Major improvement |
| Key Blind Spot | No existing code awareness | `is_actionable` outer guard at L279 | Still has gaps |
| Effort Accuracy | 3-5 days (understated) | 1-2 days (slightly understated) | Improved |
| User Problem Match | Low (solved wrong problem) | Medium (D1 solves pain, D2-3 diverge) | Improved |
| Measurement Plan | None | Weak (N=10, no rubric) | Marginal improvement |

## Final Verdict

**APPROVE WITH REVISIONS**

The gate fix at `capture.py:293` (Decision 1) is correct and should ship immediately. However, the following revisions are required before proceeding with the full plan:

1. **Address the `is_actionable` outer guard** (line 279). Either widen `_ACTION_PATTERNS` to catch more natural-language captures, or have `/task`/`/idea` prefixes bypass this guard explicitly. The 4-line fix is inert without this.

2. **Add intent-aware branching to `handle_extraction_confirm`** (line 519). Non-task intents must NOT create Notion Tasks. Ideas should get "Save Idea / Skip", reflections "Add to Journal / Skip". This is 15-20 lines, not 4.

3. **Defer Decisions 2-3 until post-fix observation.** Ship Decision 1, observe real capture behavior for 1-2 weeks, then decide if command prefixes and vault routing are justified by observed failures. The Bias Detector and Cost-Benefit agents independently reached the same conclusion: Decisions 2-3 exist to satisfy the grill, not the user.

4. **Scope Decision 3 down if pursued.** Drop "update -> project file" (no function exists, wrong-project writes are destructive). Use frontmatter `intent: idea` tags in `vault/Inbox/` instead of subdirectories. Let Obsidian Dataview handle filtering.

5. **Replace N=10 measurement with ongoing logging.** Add extraction decision logging at the gate (was extraction shown or discarded?). This is more useful than a one-time 10-capture spot check.

The proposal earns its pass by correctly identifying the root cause and constraining scope -- a dramatic improvement over the prior two attempts. The core fix is sound; the surrounding enhancements need sequencing discipline.

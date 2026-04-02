---
type: report
command: grill
date: 2026-03-29
status: active
tags: [adversarial-review, quality-gate, bug-fixes]
target: Bug-fix plan (5 agents for 4 bugs + rolling memo context)
---

# Grill Report: Bug-Fix Plan

**Target**: 5 parallel agents fixing 4 bugs + rolling memo context
**Date**: 2026-03-29
**Griller team**: 7 independent adversarial agents (zero shared context)

## Executive Summary

Of the 5 proposed fixes, **only 2 are genuine bugs** (graduation lastrowid=0, rolling memo missing context). Bug 1 (search filter) may not exist as described -- the `/find` direct path doesn't use filter presets, and the type string may be wrong. Bug 3 (Sunday collision) is not a correctness issue in PTB's async model. Bug 4 (silent failures) is a real operational gap but the proposed blanket fix creates flood-control cascades and topic pollution. The Alternatives agent found the root cause: **3/5 bugs share a "forgot to register X" pattern** solvable by a `@scheduled_job` decorator and denylist-with-fallback filter. The Cost-Benefit agent delivered the session's most important meta-finding: "The grill sessions have now cost more analysis time than the implementation would have taken."

## Challenged Decisions

| # | Decision | Avg | Weakest Lens | Key Challenge |
|---|----------|-----|-------------|---------------|
| 1 | Add rolling-memo to find/drift filters | **4.3** | User (2) | May not be a bug; type string likely wrong; drift feedback loop risk |
| 2 | Fix graduation lastrowid=0 | **6.7** | Risk (5) | Real bug; add status check to prevent resurrecting expired proposals |
| 3 | Move drift to 18:15 | **5.3** | Cost (3) | Not a correctness bug in async; cosmetic schedule shift |
| 4 | Add _notify_job_failure to 11 handlers | **5.7** | Risk (3) | Flood cascade if Telegram is down; topic pollution; use decorator instead |
| 5 | Load rolling-memo.md as vault context | **6.0** | User (4) | Real gap; needs hard 30-entry cap; prompt injection persistence risk |
| 6 | Prompt fix for template text | **7.0** | -- | Correct, uncontroversial |
| 7 | 5 parallel agents for 41 lines | **4.0** | Cost (2) | 3 agents modify scheduled.py = merge conflicts; overhead > implementation |

## What To Actually Ship

Based on convergence across all 7 lenses:

### Ship Now (genuine bugs, high confidence)

**Fix 2 (graduation lastrowid)** -- BUT make the hash query unconditional (not just fallback) and add `AND status = 'pending'` to prevent resurrecting expired proposals. Use `RETURNING id` if SQLite 3.35+.

**Fix 5 (rolling memo context)** -- BUT add a hard cap: load only last 7 entries, not the full file. Use Alternative D (SQLite-backed entries) long-term.

**Fix 6 (prompt instructions)** -- Ship as-is.

### Ship With Revision

**Fix 4 (failure notifications)** -- Don't wire into all 11 handlers individually. Instead, implement the **`@scheduled_job` decorator** from the Alternatives agent:
```python
@scheduled_job("morning_briefing", notify_on_failure=True)
async def job_morning_briefing(context):
    ...
```
This also consolidates `_record_job_run()` (currently duplicated in every job). Apply selectively: enable notifications only for user-facing jobs (briefing, evening, drift, graduation), not infrastructure jobs (reindex, keyword expansion).

### Skip

**Fix 1 (search filter type)** -- Verify first: (a) does `/find` even use `filters_for_command`? (b) what type string does the indexer assign? The Feasibility Auditor found the type is likely `"report"`, not `"rolling-memo"`. The Bias Detector found the existing allowlist already excludes system content from `ghost`/`challenge`. Don't add `rolling-memo` to `drift` -- it creates a provenance feedback loop.

**Fix 3 (drift 18:15)** -- Not a correctness bug. WAL mode handles concurrent reads. PTB's async event loop doesn't deadlock on simultaneous coroutines. Skip unless you observe actual contention.

## Confidence Scores

| Fix | Devil | Feasibility | Bias | Cost | Alts | Risk | User | **Avg** |
|-----|-------|-------------|------|------|------|------|------|---------|
| 1. Filter type | 4 | 5 | 3 | 8 | 6 | 4 | 2 | **4.6** |
| 2. lastrowid | 5 | 9 | 8 | 6 | 6 | 5 | 2 | **5.9** |
| 3. Drift 18:15 | 3 | 10 | 4 | 3 | 7 | 7 | 3 | **5.3** |
| 4. Job failures | 4 | 8 | 6 | 7 | 8 | 3 | 7 | **6.1** |
| 5. Memo context | 4 | 9 | 9 | 6 | 7 | 4 | 4 | **6.1** |

## The Meta-Finding

> "The grill sessions have now cost more analysis time than the implementation would have taken. 3 commits, one agent, 20 minutes." -- Cost-Benefit Challenger

> "3/5 bugs share a root cause: missing automation when new things enter the system. A decorator + denylist-with-fallback prevents the entire category." -- Alternative Path Explorer

> "Four rounds of grills create pressure to find bugs. Marginal observations get promoted to bugs." -- Bias Detector

**The honest answer**: Ship fixes 2, 4 (as decorator), 5 (with cap), and 6. Skip 1 and 3. Do it in one agent, one commit, 30 minutes. Stop grilling.

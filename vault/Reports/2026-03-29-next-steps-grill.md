---
type: report
command: grill
date: 2026-03-29
status: active
tags: [adversarial-review, quality-gate, next-steps]
target: Claude's "next steps" recommendation (stop building, start using)
---

# Grill Report: Next Steps Recommendation

**Target**: "Stop building, start using, check back in 30 days"
**Date**: 2026-03-29
**Griller team**: 7 independent adversarial agents (zero shared context)

## Executive Summary

The "stop building, start using" advice is **directionally correct and the best recommendation this system has received** -- but the evaluation mechanisms have specific bugs that will produce false negatives, causing you to incorrectly conclude features don't work when the real failures are upstream. The Risk Amplifier found 4 concrete bugs that must be fixed before going live: `type: rolling-memo` is excluded from all search filter presets (kill criterion 3 can mathematically never pass), `lastrowid=0` on INSERT OR IGNORE means graduation proposals exist in the DB but never get sent to Telegram, Sunday 6pm has two jobs firing simultaneously, and there are zero Telegram notifications for job failures (30 days of silent failures). The Bias Detector found the most important ground truth: the rolling memo is already running but producing **identical template text across 20+ days** -- "Open Thread: Balancing depth vs breadth" repeated verbatim every entry. The system is running but not working, and no one in the review chain checked the actual output.

## Challenged Decisions

| # | Decision | Avg | Weakest Lens | Key Challenge |
|---|----------|-----|-------------|---------------|
| 1 | Start using bot daily | **6.3** | Devil (4) | Forced use produces compliance data, not organic signal |
| 2 | Restart bot | **6.2** | Devil (3) | 40+ modified unstaged files; no preflight checklist |
| 3 | Wait for Sunday graduation | **4.7** | Risk (3) | `lastrowid=0` bug means proposals exist but never send |
| 4 | Check in 30 days with kill criteria | **5.3** | Risk (2) | Single checkpoint after 30 days of potentially silent failures |
| 5 | Defer temporal edges (90+ days) | **7.5** | Devil (5) | Correct call; fix verified_at write bug NOW to collect data |
| 6 | Defer consolidation (30K tokens) | **6.5** | Bias (4) | Rolling memo already running but output is template text |
| 7 | Defer DBSCAN v2 | **7.8** | -- | Correct call; SQL v1 is simpler and already met kill criterion |
| 8 | "Everything is infrastructure" | **4.0** | Devil (3) | Non-falsifiable holding pattern; doesn't define "real usage" |

## The 4 Bugs to Fix Before Going Live

These were found by the Risk Amplifier and Feasibility Auditor reading actual production code:

### Bug 1: Rolling memo invisible to search (Risk: 2/10)
`search_filters.py` presets for `find`, `today`, `drift`, `ideas`, `emerge` use `file_types=["concept", "project", "journal"]`. The rolling memo has `type: rolling-memo`. It will NEVER appear in filtered search results. Kill criterion 3 ("memo loaded in >= 5 commands") can mathematically never pass.
**Fix**: Add `"rolling-memo"` to relevant search filter presets.

### Bug 2: Graduation proposals silently not sent (Risk: 3/10)
`scheduled.py` line ~687: `if row_id:` gates the Telegram send. SQLite's `lastrowid` returns 0 on `INSERT OR IGNORE` when the row already exists. A re-detected cluster (same captures after restart) inserts with IGNORE, gets `lastrowid=0`, and the proposal sits in the DB forever without being sent. The 14-day TTL expires it.
**Fix**: After INSERT OR IGNORE, query for the existing row when `lastrowid == 0` and send if it has no `message_id`.

### Bug 3: Sunday 6pm job collision (Risk: 4/10)
`job_drift_report` (expensive Claude call) and `job_dashboard_refresh` (alert checks, attention scores) both fire at `time(18, 0)` on Sunday. Both write to different topics but contend for DB writes.
**Fix**: Stagger to 6:00pm and 6:15pm.

### Bug 4: No Telegram notification for job failures (Risk: 2/10)
All scheduled jobs use `except Exception: logger.exception(...)` -- errors are logged to a file the user never reads. After 30 days, `evaluate_kill_criteria.py` fails on 3/5 criteria and you have 30 days of log files to triage.
**Fix**: Add `_send_to_topic(context.bot, "brain-daily", "Job {name} failed: {error}")` in the exception handler.

## Per-Lens Critiques

### Devil's Advocate (avg ~4.5/10)
- "Forced daily use generates compliance data, not organic signal. If the system isn't naturally compelling, that's a signal -- not a problem to override with discipline."
- "Everything is infrastructure" is non-falsifiable -- it provides indefinite cover for over-engineering.
- Fading content detector at 11% (7/61 docs) is either mis-calibrated or evidence the vault is too small.

### Feasibility Audit (avg ~8/10 -- most positive)
- Architecture holds. Boot sequence is resilient. Graduation flow is complete.
- **Key action**: Verify `launchctl list com.brain.telegram-bot` shows process active. If not loaded, no scheduled jobs will ever fire.
- **Key action**: Verify `handlers/graduation.py:register()` is called from `handlers/__init__.py`.
- Rolling memo is working but "Open Thread" / "Carry Forward" are boilerplate -- prompt doesn't have access to its own prior output.

### Bias Detection (avg ~5/10)
**Ground truth discovery**: The rolling memo (`vault/Reports/rolling-memo.md`) has 20+ entries with IDENTICAL "Open Thread: Balancing depth vs breadth across ICOR dimensions" and "Carry Forward: Continue momentum on strongest dimension" text. Every single day. The "Decisions Made" field is "none" across every entry. This is template generation, not knowledge capture.

"The 'stop building, start using' recommendation defines success as the system running, when the actual success criterion should be whether the system changes the user's behavior or thinking over 30 days. That criterion is not defined anywhere."

### Cost-Benefit Challenge (avg ~5/10)
- Daily use: **9/10** -- "Non-negotiable. Every other decision is downstream of this one."
- Kill criteria: **7/10** -- but "write the criteria TODAY, not in 30 days."
- Weighted RRF: **2/10** -- "Calibrated against synthetic queries. The most dangerous shipped feature."
- **Best advice**: "14-day black-box usage window. Do not fix bugs, do not tune thresholds, do not read logs. Use it as a black box and note where it fails."

### Alternative Paths (avg ~6.3/10)
**Top 3 alternatives:**
1. **Criterion-triggered resume, not calendar-triggered.** Define 3 resumption criteria NOW: capture drops below 2/day for 7 days (friction), command fails with no workaround (reliability), same manual lookup 3 times (missing feature). Build when any fires.
2. **Graduation in shadow mode.** Run detector but write proposals only to DB -- never surface to user for 30 days. After 30 days, check: "Of the N proposals, how many would I approve?" Validate before adding notification friction.
3. **Per-dimension rolling memos.** 6 files of 14 entries each vs 1 file of 50 entries. When `/ghost` runs, load only the relevant dimension memo. 6x more signal density.

**Highest-leverage action**: Fix 3 code bugs in < 2 hours (verified_at write, semantic similarity edges, trace sorting) -- touches 3 decisions, fixes the only broken user-visible behaviors.

### Risk Amplification (avg ~3.4/10)
**Top 3 risks the plan never mentions:**
1. Rolling memo becomes dominant search attractor after 2-3 weeks (largest single file + dense content = top vector result for everything)
2. First Sunday runs EVERY job simultaneously (emerge biweekly check returns True on fresh DB)
3. `evaluate_kill_criteria.py` criterion 2 (fading) returns MANUAL which counts as PASS -- you can ship to 90 days never having interacted with fading memories

### User Impact (avg ~3.8/10)
**The core truth**: "Four weeks of development delivered ~13,000 lines of infrastructure code. The vault has 61 notes, 14 classifications, and 17 inbox entries. Zero concept notes."

**Highest-impact shipped feature**: Chronological `/trace` output (7/10) -- immediately noticeable, tells a story instead of a scatter.

**What nobody fixed**: The system has a capture friction problem and a reflection habit problem. No infrastructure solves either.

**Three highest-ROI things never built:**
1. A morning prompt that requires answering (current briefing is read-only)
2. A "did you use it today?" counter displayed prominently
3. Capture friction reduction (user sends 1-2/week; system expects 10+/day)

## Confidence Scores

| Decision | Devil | Feasibility | Bias | Cost | Alts | Risk | User | **Avg** |
|----------|-------|-------------|------|------|------|------|------|---------|
| 1. Use daily | 4 | 9 | 7 | 9 | 6 | 4 | 5 | **6.3** |
| 2. Restart bot | 3 | 8 | 7 | 8 | -- | 5 | -- | **6.2** |
| 3. Sunday graduation | 5 | 7 | 6 | 3 | 7 | 3 | 6 | **5.3** |
| 4. 30-day eval | 4 | 8 | 5 | 7 | 6 | 2 | 5 | **5.3** |
| 5. Defer temporal | 5 | 9 | 5 | 9 | 7 | 4 | -- | **6.5** |
| 6. Defer consolidation | 4 | 9 | 4 | 4 | 6 | 3 | -- | **5.0** |
| 7. Defer DBSCAN v2 | 5 | 9 | 6 | 9 | -- | -- | 6 | **7.0** |
| 8. "Everything is infra" | 3 | -- | 4 | -- | 6 | 2 | 3 | **3.6** |

## Final Verdict

**Would a staff engineer approve this?**

### APPROVE WITH 4 BUG FIXES

This is the first recommendation in the entire review chain that a staff engineer would approve without major revisions. "Stop building, start using" is the correct call for a 13,000-line system serving 61 documents. The deferrals are well-reasoned with clear revisit triggers.

**Before going live (< 2 hours):**
1. Fix rolling-memo type filter exclusion
2. Fix graduation `lastrowid=0` silent non-send
3. Stagger Sunday 6pm jobs
4. Add Telegram notification for job failures

**Before the 30-day clock starts:**
1. Write kill criteria TODAY (the script may already exist -- verify and review thresholds)
2. Verify launchd is loaded and graduation handler is registered
3. Define what "real usage" means: minimum captures/day, minimum commands/week
4. Check rolling memo output quality -- if it's still producing template text, fix the prompt before relying on it as an evaluation artifact

**The uncomfortable question nobody asked:**
The system has been running for 49 days. The user has 13 daily notes (27% completion rate), 17 inbox captures, and zero graduated concepts. Is the bottleneck really infrastructure -- or is it that the system doesn't yet solve a problem the user actually has?

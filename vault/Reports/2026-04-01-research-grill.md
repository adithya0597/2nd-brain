---
type: report
command: grill
date: 2026-04-01
status: active
tags: [adversarial-review, research-grill, intelligence-layer]
target: vault/Reports/2026-04-01-notebooklm-research.md
---

# Research Grill Report: NotebookLM Intelligence Layer Recommendations

**Target**: NotebookLM Research Synthesis + 7-Step Local Pipeline Recommendation
**Date**: 2026-04-01
**Griller team**: 4 adversarial agents (Devil's Advocate, Feasibility, Cost-Benefit, User Impact)
**Sources grilled**: 5 NotebookLM notebooks cross-referenced against the original grill report

## Executive Summary

The NotebookLM research correctly validated the original grill's core findings (progressive enrichment, no webapp, morning briefing reminders). But it then OVER-CORRECTED by recommending a 7-step local extraction pipeline (GLiNER + spaCy + FlashRank + regex + FTS5 + cosine + LLM escalation) that is dramatically more complex than the problem requires. **All 4 grillers converged on the same verdict: a single Haiku/Gemini call on actionable captures (already integrated) ships intelligence in an afternoon. The 7-step pipeline ships it in a week with worse accuracy.**

The research solved problems the user does not have (cost at $0.02/day, latency at 20 captures/day, scale) while delaying the solution to the problem the user DOES have ("there is no intelligence in my 2nd brain yet").

## Challenged Recommendations

| # | Recommendation | Devil | Feasibility | Cost-Benefit | User Impact | **Avg** |
|---|---|---|---|---|---|---|
| 1 | Local-first extraction (GLiNER+spaCy) | 4 | 5 | 3 | 2 | **3.5** |
| 2 | Progressive enrichment (async) | 7 | 8 | 3 | 3 | **5.3** |
| 3 | One axis only (Intent) | 5 | - | 6 | 7 | **6.0** |
| 4 | No webapp | 6 | 10 | 10 | 5 | **7.8** |
| 5 | Morning briefing reminders | 5 | 9 | 9 | 9 | **8.0** |
| 6 | Skip Gemini Flash | 3 | - | - | - | **3.0** |
| 7 | 7-step local pipeline | 2 | 3 | 2 | 2 | **2.3** |

## Key Findings by Lens

### Devil's Advocate
- **Gemini is ALREADY integrated** in `config.py` and `ai_client.py`. The recommendation to "skip Gemini" is actually a recommendation to remove existing functionality.
- **Intent-only is insufficient** for the user's P0: project linking + date extraction + reminders require entity extraction, not just intent labels.
- **7-step pipeline directly contradicts 3 of the synthesis's own principles**: complexity death spiral (4/5 score), "start with intent only," and "halve the surface area."
- A single LLM call returns `{intent, entities, due_date, project}` in one shot. Adding fields to a prompt is trivial — no need for 7 separate pipeline stages.

### Feasibility Auditor
- **GLiNER is a research-stage library** (NAACL 2024), not production-ready. Requires PyTorch (~500MB-2GB) which may conflict with existing sentence-transformers on macOS ARM.
- **Memory footprint concern**: nomic-embed (137M params) + GLiNER (~209M params) = two transformer models in RAM on a laptop.
- **FlashRank's model** (ms-marco-MiniLM) is trained for passage reranking, not entity-to-project matching in personal captures.
- **The high-value, low-risk path**: skip GLiNER and FlashRank entirely. Use regex+dateutil for dates, FTS5+existing embeddings for project matching, LLM for the 20% remainder. 2 steps, not 7. Zero new dependencies.

### Cost-Benefit Challenger
**The definitive TCO comparison:**

| Item | 7-Step Local | LLM-Augmented (1 call) |
|---|---|---|
| API cost/year | $0 | $7-18 |
| New code | 800-1200 LOC | 50-80 LOC |
| New dependencies | 3 | 0 |
| Build time | 40-60 hours | 4-8 hours |
| Tests needed | ~100 new | ~15 new |
| Maintenance/year | ~20 hours | ~2 hours |
| **Developer cost** | **$6,000-8,000** | **$400-800** |
| **Total 1-year** | **$6,000-8,000** | **$407-818** |

The 7-step pipeline optimizes for API cost ($7-18/year) while ignoring developer cost ($6,000-8,000). **Negative ROI by a factor of 10x.**

### User Impact Skeptic
- **Morning briefing reminders (9/10)**: Ships in 30 minutes. User feels "intelligence" tomorrow morning.
- **Haiku extraction (high impact)**: Ships in 2-4 hours. ~50-100 lines of code.
- **7-step pipeline (2/10)**: Ships in 3-5 days with worse accuracy on context-dependent extractions.
- **Quote**: "The user said 'there is no intelligence yet' — that is a plea for something working NOW, not for an architecturally optimal extraction pipeline."

## What the NotebookLM Research Got RIGHT

1. **Progressive enrichment is the correct pattern** — but synchronous enrichment at 20 captures/day adds imperceptible latency (~1-2s), so async is unnecessary at this scale
2. **No webapp is correct** — validated across all notebooks and all grillers
3. **Morning briefing reminders is the highest-leverage change** — unanimously scored 8-9/10
4. **FTS5 + existing embeddings for project matching** — this specific technique works without new dependencies
5. **The "bouncer" confidence filter pattern** — already exists in the codebase, should gate LLM extraction

## What the NotebookLM Research Got WRONG

1. **GLiNER recommendation** — research-stage library, PyTorch dependency, unproven for informal personal text
2. **7-step pipeline** — trades $7-18/year API cost for $6,000-8,000 developer cost
3. **"Skip Gemini"** — Gemini is already integrated in config.py and ai_client.py
4. **Local-first absolutism** — romanticizes local ML without accounting for solo developer reality
5. **Progressive enrichment as async** — unnecessary at 20 captures/day; synchronous is simpler

## Final Verdict: The True MVP

**REJECT the 7-step local pipeline. APPROVE the following 3-step plan:**

### Step 1: Morning Briefing Reminders (Ship TODAY — 30 minutes)
- Add `due_date TEXT` column to `action_items` table
- Add SQL query to morning briefing: `WHERE due_date <= date('now') AND status='pending'`
- Add `/remind YYYY-MM-DD description` command for manual date setting
- User feels "intelligence" tomorrow morning

### Step 2: Structured LLM Extraction (Ship THIS WEEK — 4-8 hours)
- Gate on `is_actionable` regex (already exists at classifier.py:71-75)
- Call Gemini Flash (already integrated in ai_client.py:64-132) with structured prompt
- Extract: `{intent, project_name, people, due_date, actions}`
- Match `project_name` against `notion-registry.json` cache via fuzzy string match
- Write enriched data to action_items + captures_log
- Optional: `run_once()` for same-day time-specific reminders (~10 lines)

### Step 3: Observe and Iterate (2 weeks of real usage)
- Track extraction accuracy on real captures
- Track how many captures trigger LLM escalation vs short-circuit
- Only then consider local models IF cost or accuracy is a measured problem
- Consider Streamlit dashboard IF demo need is validated

**Total cost**: ~$400-800 developer time + $7-18/year API. Ships in 1-2 days.
**vs 7-step local pipeline**: ~$6,000-8,000 developer time + $0/year API. Ships in 1-2 weeks.

The user asked for intelligence. Ship intelligence, not infrastructure.

---
type: report
command: grill
date: 2026-04-02
status: active
tags: [adversarial-review, quality-gate, data-safety]
target: Hybrid Mock Data Generator Plan
---

# Grill Report: Mock Data Generator Plan — Data Safety Focus

**Target**: Hybrid Mock Data Generator implementation plan
**Date**: 2026-04-02
**Griller team**: 7 independent adversarial agents (zero shared context)
**User's key concern**: "make sure this plan wouldn't affect my personal real data"

## Executive Summary

The plan has a **critical data safety flaw** that 5 of 7 grillers independently discovered: `DB_PATH` and `VAULT_PATH` env overrides **do not exist** in `config.py` — they are hardcoded. Running the bot with `DB_PATH=data/brain_demo.db` would have zero effect; the bot would still use the real `brain.db` and write to the real `vault/`. Additionally, the plan is over-engineered: 900 lines + external datasets + LLM story arc for ~350 rows when a ~150-line hardcoded script produces identical demo quality.

**Composite score: 4.8/10** — Sound isolation concept, dangerous implementation gaps, excessive complexity.

## DATA SAFETY VERDICT

### 7 Pathways Where Real Data Could Be Affected

| # | Pathway | Severity | Status |
|---|---------|----------|--------|
| 1 | `config.py` hardcodes `DB_PATH` — env override doesn't exist | CRITICAL | **Not implemented** |
| 2 | `config.py` hardcodes `VAULT_PATH` — no override at all | CRITICAL | **Not implemented** |
| 3 | Existing `generate_eval_data.py` writes to real `brain.db` by default | CRITICAL | Already happening |
| 4 | Rolling-memo writes to real `vault/Reports/` unconditionally | HIGH | Already happening |
| 5 | Vault indexer scans `vault/Demo/` into whichever DB (not in `_EXCLUDED_DIRS`) | HIGH | Would happen |
| 6 | Notion sync pushes fake data to real Notion workspace | CRITICAL | Would happen if bot runs |
| 7 | Telegram messages go to real group chat | MEDIUM | Would happen if bot runs |

### Required Fixes Before Implementation

1. Add to `config.py`: `DB_PATH = Path(os.environ.get("BRAIN_DB_PATH", PROJECT_ROOT / "data" / "brain.db"))`
2. Add to `config.py`: `VAULT_PATH = Path(os.environ.get("BRAIN_VAULT_PATH", PROJECT_ROOT / "vault"))`
3. Add `"Demo"` to `_EXCLUDED_DIRS` in `vault_indexer.py`
4. Create `demo-env.sh` wrapper that sets DB_PATH, VAULT_PATH, and **unsets** NOTION_TOKEN + GROUP_CHAT_ID
5. Add `.obsidianignore` with `Demo/` entry
6. Add `data/brain_demo.db*` and `vault/Demo/` to `.gitignore`

## Challenged Decisions

| # | Decision | Avg Score | Weakest Lens | Key Challenge |
|---|----------|-----------|-------------|---------------|
| 1 | Schema copy via .schema dump | 5.3 | Feasibility (5) | vec0 shadow tables break; use conftest _SCHEMA_SQL or migrate-db.py instead |
| 2 | vault/Demo/ isolation | 3.7 | Devil (2) | VAULT_PATH not overridden; vault indexer scans Demo/; Obsidian shows files |
| 3 | External datasets (Holistix/CLINC150) | 2.4 | Cost (1), User (1) | CLINC150 is wrong domain; existing 64 hand-written texts are better |
| 4 | LLM story arc generator | 2.9 | Cost (1) | Non-deterministic, costs money, a YAML file does the same thing |
| 5 | DB_PATH env override | 5.0 | Bias (3) | Override doesn't exist in code; plan states it as fact |
| 6 | ~900 lines scope | 4.7 | Cost (2) | 10x complexity for 1.2x coverage; ~150 lines of hardcoded INSERTs suffices |
| 7 | Single transaction with rollback | 5.7 | Bias (5) | Only protects DB, not filesystem; vault writes are not transactional |
| 8 | Relative dates | 7.3 | Devil (6) | Sound; add --date-anchor for reproducibility |
| 9 | Bug tests separate | 8.3 | — | Best decision in the plan; decouple and do first |
| 10 | --clean flag | 5.3 | User (2) | Must also clean WAL/SHM sidecar files; `rm` command suffices |
| 11 | Data safety claim | 2.7 | Devil (2), Bias (3) | Asserted, not demonstrated; multiple unverified assumptions |

## Best Alternative Path (from Agent 5)

**Generate only leaf inputs (captures + journals + vault files), then run the bot's real derivation pipeline to populate everything else.**

Instead of synthetically generating 15 tables, seed only captures_log + journal_entries + vault .md files. Then run:
- `vault_indexer.run_full_index()`
- `engagement.backfill_engagement()`
- `dimension_signals.compute_dimension_signals()`
- `community.update_community_ids()`

This guarantees internal consistency (real code computed the derived data), exercises the actual pipeline, and reduces the generator from 900 lines to ~200.

## Blind Spots Exposed

1. **Notion sync pushes fake data upstream** (Risk only) — If NOTION_TOKEN is set, nightly sync pushes fake journals/actions to real Notion
2. **Module-level path caching** (Devil + Feasibility) — `rolling_memo.py` and other modules compute paths at import time; runtime config changes don't propagate
3. **Hardcoded vault_edge node IDs** (Risk only) — `gen_vault_edges()` uses IDs from real DB; demo DB has different auto-increment sequences
4. **Telegram messages to real group** (Risk only) — Demo bot sends to same GROUP_CHAT_ID with fake dashboards/briefings
5. **notion-registry.json is shared** (Risk only) — Demo bot reads/writes same registry, potentially corrupting real Notion mappings

## Confidence Scores

| Decision | Devil | Feasibility | Bias | Cost | Alternatives | Risk | User | **Avg** |
|----------|-------|-------------|------|------|-------------|------|------|---------|
| 1. Schema copy | 5 | 5 | 6 | 3 | 7 | 8 | 3 | **5.3** |
| 2. vault/Demo/ | 2 | 6 | 5 | 2 | 8 | 4 | 5 | **3.7** |
| 3. External datasets | 3 | 3 | 5 | 1 | 9 | 6 | 1 | **2.4** |
| 4. LLM story arc | 3 | 4 | 4 | 1 | 8 | 6 | 2 | **2.9** |
| 5. DB_PATH override | 4 | 9 | 3 | 5 | 6 | 4 | 7 | **5.0** |
| 6. ~900 lines | 5 | 6 | 5 | 2 | 7 | 5 | 3 | **4.7** |
| 7. Single transaction | 5 | 8 | 5 | 4 | 6 | 5 | 7 | **5.7** |
| 8. Relative dates | 6 | 8 | 8 | 7 | 6 | 7 | 7 | **7.3** |
| 9. Bug tests separate | 9 | 7 | 8 | 8 | 8 | 8 | 8 | **8.3** |
| 10. --clean flag | 6 | 7 | 6 | 4 | 6 | 7 | 2 | **5.3** |
| 11. Data safety claim | 2 | 9 | 3 | 6 | 6 | 3 | 7 | **2.7** |

## Final Verdict

**APPROVE WITH MAJOR REVISIONS**

### What must change:
1. **Fix data safety first**: Add env overrides for DB_PATH + VAULT_PATH to config.py, add Demo/ to vault indexer exclusions, create demo-env.sh wrapper
2. **Drop external datasets entirely**: Existing text pools are better for this domain
3. **Drop LLM story arc**: Use a static YAML/dict scenario instead
4. **Simplify to ~200 lines**: Seed captures + journals + vault files, then run bot's derivation pipeline for everything else
5. **Ship bug tests first, independently**: Don't gate them behind demo data work

### What is strong enough to keep:
- Separate demo DB (brain_demo.db) concept
- vault/Demo/ isolation (after VAULT_PATH override is added)
- Relative dates with seed for reproducibility
- --demo flag on the generator
- --clean for cleanup

### Recommended simplified approach:
1. Add env overrides to config.py (2 lines)
2. Add Demo/ to vault indexer exclusions (1 line)
3. Create demo-env.sh (10 lines)
4. Write ~200-line seed script: hardcoded captures + journals + vault files
5. Run bot's derivation pipeline to populate engagement/signals/brain_level/etc.
6. Write 5 bug regression tests separately (~120 lines)

**Total: ~330 lines across 3 files instead of ~900 lines across 4 files, with stronger data safety guarantees.**

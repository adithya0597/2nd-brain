# HANDOFF: Second Brain — Post-Capstone Grill

**Date**: 2026-03-30
**Session**: Marathon grill session — 14 /grill-me invocations, 81 adversarial agents, 11 saved reports
**Status**: All code quality issues identified. Capstone grill complete. Ready for final fixes + graph_maintenance wiring.

---

## Goal

Two immediate tasks:
1. **Capstone grill fixes** — 7 code quality, content accuracy, and dead code fixes identified by the capstone retrospective
2. **Wire graph_maintenance.py** into 3 integration points (command + scheduled job + dashboard)

Then: **stop building, start using for 30 days.**

---

## Current Progress

### Session Output: 11 Grill Reports

| # | Report | Target | Verdict |
|---|--------|--------|---------|
| 1 | `vault/Reports/2026-03-28-grill.md` | Graph memory research (12 decisions) | APPROVE WITH REVISIONS |
| 2 | `vault/Reports/2026-03-28-meta-grill.md` | Author's response to grill (12 claims) | APPROVE WITH REVISIONS |
| 3 | `vault/Reports/2026-03-29-grill.md` | Week 4 evaluation plan (synthetic data) | REJECT methodology, APPROVE conclusions |
| 4 | `vault/Reports/2026-03-29-next-steps-grill.md` | "Stop building, start using" plan | APPROVE WITH 4 BUG FIXES |
| 5 | `vault/Reports/2026-03-29-bugfix-grill.md` | 5 bug fixes plan | APPROVE 3 of 5. Skip 2. |
| 6 | `vault/Reports/2026-03-30-email-grill.md` | MoJo email v2 (750 words) | REJECT. Rewrite. |
| 7 | `vault/Reports/2026-03-30-email-v3-grill.md` | MoJo email v3 (220 words) | APPROVE WITH REVISIONS |
| 8 | `vault/Reports/2026-03-30-content-grill.md` | LinkedIn Part 2 post (500→202 words) | APPROVE WITH 5 FIXES |
| 9-10 | (direct verdicts, not saved) | Bug fix results + infrastructure reality check | APPROVE / DO NOT PUBLISH |
| 11 | `vault/Reports/2026-03-30-capstone-grill.md` | Full project retrospective (7 dimensions) | B+ architecture, D- usage |

### Capstone Grill Scores

| Dimension | Score | Key Finding |
|-----------|-------|-------------|
| Architecture | B+ (8.7/10) | Core decisions strong. SQLite, FEA, RRF, outbox all 8-9/10 |
| Code Quality | 6.5/10 | Critical: event loops in thread pool, raw sqlite3, unbounded threads |
| Test Coverage | 5/10 | Post-write hook chain always patched out. 10/13 jobs untested |
| Execution Discipline | 4/10 | Numbers drift upward. Fabricated claims caught. 3 direction changes |
| Usage Reality | 3/10 | 5/22 commands used. search_log=0. Both APIs broken. Engagement: 2.0/10 |
| Claims Accuracy | 75% | 30 TRUE, 7 PARTIAL, 3 FALSE, 5 UNVERIFIABLE across 48 claims |
| Strategy | 6/10 | Personal tool 6, Portfolio 7, Product 3 |

### Prior Session Fixes (already shipped)

- P0 crashes fixed: `int(None)` dashboard, AI client guard, error handler
- Notion 401 handling, pending captures SQL guard
- Boot sequence isolation (each builder in own try/except)
- Network timeouts (30s connect/read/write)
- Graph rebuilt: 2→4 edge types, 146→381 edges, 0→145 chunks, stale→4 communities

### Database State

- 72 vault nodes, 381 edges (67 wikilink, 79 icor_affinity, 98 semantic_similarity, 71 tag_shared, 66 community)
- 14 journal entries, 14 captures, 0 search_log, 0 concepts graduated
- `ANTHROPIC_API_KEY` and `NOTION_TOKEN` need to be set in `.env` before use

---

## What Worked

1. **Grill skill** — caught fabricated claims (OpenClaw stats, exercise correlation, "lived in for months"), dead infrastructure (sqlite-vec not loading, 2/4 edge types empty), motivated reasoning, and real bugs
2. **Capstone 7-dimension scan** — architecture, code quality, tests, evolution, usage, claims, strategy gave complete picture
3. **Feasibility agents reading actual code** — found `generate_text` doesn't exist in `ai_client.py`, `verified_at` never written, graduation proposals silently not sent
4. **Direct verdicts** for obvious cases (bug fix results, infrastructure reality check) — no agents needed
5. **Content iteration**: email v1 (REJECT) → v2 (REJECT) → v3 (APPROVE) showed the skill driving real improvement

## What Didn't Work

1. **Grilling completion reports** — results don't need adversarial review, plans do
2. **14 grill invocations in one session** — context exhaustion. The Cost-Benefit agent said it best: "The grill sessions have now cost more analysis time than the implementation would have taken"
3. **Synthetic data methodology** — pre-declared outcomes, threshold gerrymandering, circular reasoning. Rejected unanimously.
4. **Numbers in content without DB verification** — every number that wasn't verified against a live query turned out wrong
5. **Rolling memo producing identical template text** — shipped as "done" without checking actual output

---

## Next Steps

### Step 1: Capstone Grill Fixes (~1 hour, 7 parallel agents)

The plan is at the end of this session's conversation. Summary:

**Agent 1 — Event loops + raw SQLite** (handlers/commands.py + handlers/scheduled.py):
- Replace `asyncio.new_event_loop()` with `asyncio.run()` in commands.py:126-150
- Replace 3 raw `sqlite3.connect()` with `get_connection()` in scheduled.py:62,87,675

**Agent 2 — Unbounded threads + docstring** (core/vault_ops.py + core/db_ops.py):
- Replace `threading.Thread(daemon=True).start()` with `executor.submit()` from async_utils
- Add WARNING docstring to `execute()` about INSERT OR IGNORE + lastrowid=0

**Agent 3 — FALSE claims** (content/linkedin-article.md + content/medium-article.md):
- "30 references/dimension" → "5 references/dimension (30 total)"
- "19 slash commands" → "23 commands"
- "threshold 0.55" → "threshold 0.52"

**Agent 4 — Stale numbers** (content/linkedin-post-part2.md + content/medium-article.md):
- Edges: 315→381, LOC: verify with `wc -l`, Tests: verify with `pytest --collect-only`
- Channels: 3→4, Tables: verify with DB count, Modules: recount after dead code removal

**Agent 5 — Dead code removal**:
- Delete `core/app_home_builder.py` (orphaned Slack artifact, zero imports)
- Update `core/CLAUDE.md` to remove the row

**Agent 6 — Post-write hook E2E test** (NEW tests/test_post_write_hooks.py):
- The system's core innovation has zero end-to-end tests
- Let hooks fire for real (vault_index + FTS), mock only embedding model

**Agent 7 — Verify** (runs after 1-6):
- Full pytest, grep for removed patterns, DB query verification

### Step 2: Wire graph_maintenance.py (~15 lines across 2 files)

DO NOT delete `core/graph_maintenance.py`. Wire it into 3 places:

1. **`handlers/commands.py`** — register `/maintain` in `_COMMAND_MAP` → runs `run_maintenance()`, formats output, sends to `brain-dashboard`
2. **`handlers/scheduled.py`** — add `job_graph_maintenance` weekly Sunday 4am before reindex. Send orphan/density summary to `brain-dashboard` if orphans found.
3. **`handlers/scheduled.py`** `job_dashboard_refresh` — import `compute_graph_density()` and include density metric in dashboard output

### Step 3: Set API Credentials

- Set `ANTHROPIC_API_KEY` in `scripts/brain-bot/.env`
- Regenerate Notion token at https://www.notion.so/my-integrations → update `NOTION_TOKEN` in `.env`
- Restart bot: `cd scripts/brain-bot && python app.py`

### Step 4: Use the Bot for 30 Days

- Journal daily (the `/close` command is the most-used feature at 20 runs — keep that going)
- Run `/find`, `/ideas`, `/ghost` at least once each to exercise the dormant RAG pipeline
- Check graduation proposals on Sundays (5:15am)
- At day 30: run `python scripts/evaluate_kill_criteria.py` against real data

---

## Open Questions

1. **LOC count discrepancy**: Capstone feasibility measured ~17K, plan says ~35K. Run `find scripts/brain-bot -name "*.py" | xargs wc -l` to get the real number before updating content.
2. **Test count**: Plan says 980+, capstone measured 774. Run `pytest --collect-only | tail -1` to get the real number.
3. **Investor dashboard**: Still on the roadmap? The prior HANDOFF had a Track 1 for investor-ready visualization. Unclear if this is still needed.
4. **Engagement interventions**: The prior HANDOFF listed 4 Telegram-native features (evening reply-as-journal, morning nudge, 3-day silence nudge, richer dashboard). Still desired?

---

## Key Files

### Grill Reports (this session)
| File | Content |
|---|---|
| `vault/Reports/2026-03-28-grill.md` | Original research grill |
| `vault/Reports/2026-03-28-meta-grill.md` | Meta-analysis of grill response |
| `vault/Reports/2026-03-29-grill.md` | Week 4 evaluation methodology |
| `vault/Reports/2026-03-29-next-steps-grill.md` | "Stop building" plan |
| `vault/Reports/2026-03-29-bugfix-grill.md` | Bug fix plan |
| `vault/Reports/2026-03-30-email-grill.md` | MoJo email v2 |
| `vault/Reports/2026-03-30-email-v3-grill.md` | MoJo email v3 |
| `vault/Reports/2026-03-30-content-grill.md` | LinkedIn Part 2 post |
| `vault/Reports/2026-03-30-capstone-grill.md` | Full project retrospective |

### Content (ready to publish after number fixes)
| File | Status |
|---|---|
| `content/linkedin-post-part2.md` | 202 words, needs 2 number fixes (edges, tests/LOC) |
| `content/linkedin-article.md` | Needs 3 FALSE claim fixes + stale number updates |
| `content/medium-article.md` | Needs 3 FALSE claim fixes + stale number updates |
| `content/linkedin-diagram.excalidraw` | Ready (before/after graph visual) |

### Code to modify (Step 1)
| File | Change |
|---|---|
| `handlers/commands.py:126-150` | Replace asyncio.new_event_loop() |
| `handlers/scheduled.py:62,87,675` | Replace raw sqlite3.connect() |
| `core/vault_ops.py:80` | Replace threading.Thread with executor.submit |
| `core/db_ops.py:21` | Add lastrowid WARNING docstring |
| `core/app_home_builder.py` | DELETE (orphaned Slack artifact) |
| `core/CLAUDE.md` | Remove app_home_builder row |
| `tests/test_post_write_hooks.py` | NEW — E2E test for hook chain |

### Code to modify (Step 2)
| File | Change |
|---|---|
| `handlers/commands.py` | Register `/maintain` command |
| `handlers/scheduled.py` | Add weekly graph_maintenance job + density in dashboard |

---

## Session Statistics

- **14 /grill-me invocations** across 2 days
- **81 adversarial agents** deployed (7 per grill + 2 focused verification agents)
- **11 saved grill reports** in vault/Reports/
- **~200K+ words** of adversarial analysis generated
- **Key discoveries**: fabricated OpenClaw stats, dead Gemini client, sqlite-vec not loading, exercise correlation invented, rolling memo template text, motivated reasoning in meta-analysis, 2 broken API credentials as root cause of D- usage

---

## How to Continue

```
claude -r
```

Then: "Read HANDOFF.md. Execute the capstone grill fixes (Step 1: 7 parallel agents for code quality + content + dead code + E2E test), then wire graph_maintenance.py into 3 integration points (Step 2). After that, set API credentials (Step 3) and start using the bot daily."

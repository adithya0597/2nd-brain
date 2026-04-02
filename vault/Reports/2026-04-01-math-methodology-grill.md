---
type: report
command: grill
date: 2026-04-01
status: active
tags: [adversarial-review, quality-gate, mathematical-methods]
target: Mathematical Methodologies Implementation & Integration Analysis
---

# Grill Report: Mathematical Methodologies — Implementation & Integration

**Target**: 13 mathematical methodologies in `scripts/brain-bot/core/`
**Date**: 2026-04-01
**Griller team**: 7 independent adversarial agents (zero shared context)

## Executive Summary

The 13 mathematical methodologies are real, implemented, and mostly wired together — but the system suffers from three fundamental problems exposed across all 7 lenses:

1. **A math bug**: The L2-to-similarity formula (`1 - d/2`) is a linear approximation of the correct `1 - d²/2`, producing distorted edge weights (flagged by 3/7 lenses)
2. **Massive over-engineering for actual usage**: The sole user has produced 17 captures in 3 weeks, 0 search queries, 0 completed actions, and 4/6 dimensions frozen. The system optimizes for analyzing a rich knowledge base that does not yet exist (flagged by 4/7 lenses)
3. **Dead code falsely claimed as integrated**: `get_structural_gaps()`, `get_community_members()`, classifier `_merge_scores()`, and the zero-shot tier are effectively dead in production. The `engage` command has column name mismatches that would cause runtime failures (flagged by 5/7 lenses)

**Composite score: 3.8/10** — The mathematical building blocks are individually sound, but their integration is shallow, their calibration is absent, and their value is unproven against actual usage data.

## Challenged Decisions

| # | Decision | Avg Score | Weakest Lens | Key Challenge |
|---|----------|-----------|-------------|---------------|
| 1 | Two cosine similarity implementations | 4.1 | User Impact (2) | Unnecessary duplication; NumPy version has no zero-norm guard |
| 2 | Louvain community detection integrated | 3.0 | User Impact (1) | 2/3 query functions are dead code; 89 files too small for meaningful communities |
| 3 | RRF with per-command weights | 4.3 | User Impact (2) | Weights are untested guesses; search_log is write-only with no reader |
| 4 | BFS at configurable depth | 5.1 | Risk (4) | Best-scoring decision; appropriate simplicity; depth config is mildly academic |
| 5 | L2-to-similarity formula correct | 3.4 | Devil (3) | **Formula is wrong**: uses `1-d/2` instead of `1-d²/2`; monotonic but distorted |
| 6 | Matryoshka truncation preserves quality | 5.0 | User Impact (1) | Technically correct; premature optimization at 89 files (768-dim fits trivially) |
| 7 | 5-tier classification cascade | 3.7 | Bias (3) | Document describes wrong execution order; zero-shot and embedding tiers are redundant |
| 8 | Engagement/Brain Level calibrated | 3.1 | Bias (2) | Momentum formula rewards returning from inactivity; `engage` command has broken SQL |
| 9 | Event-driven vault write pipeline | 4.3 | User Impact (2) | Good architecture; fire-and-forget with no retry; entire pipeline untested (PYTEST guard) |
| 10 | Community bridge nodes enrich context | 2.9 | User Impact (1) | Bridge nodes are topic-agnostic hubs; /connect never executed by the user |
| 11 | All 13 methods integrated (no dead code) | 3.4 | Risk (2) | At least 3 dead functions, 1 redundant tier, column name mismatches in engage SQL |

## Per-Lens Critiques

### Devil's Advocate (Avg: 4.2)
Strongest challenges: The L2-to-similarity formula is **not** the correct conversion (it is a linear approximation that diverges at intermediate values). The engagement momentum formula has a discontinuity: returning from zero activity gets a perfect 10.0 momentum score. The "5-tier cascade" described in documentation does not match the actual code execution order. Bridge nodes inject globally-connected hub documents regardless of query relevance.

### Feasibility Audit (Avg: 5.5)
Key findings: `get_neighbors` BFS in `graph_ops.py` is dead code — the actual BFS used in context loading is a wikilink-only reimplementation in `vault_indexer.get_linked_files`. The post-write pipeline has zero test coverage (PYTEST_CURRENT_TEST guard skips it entirely). 1,335 tests pass but they do not exercise the most critical integration point. Community detection and scoring formulas are the weakest links.

### Bias Detection (Avg: 3.5)
Systemic patterns found:
1. **Retrospective rationalization**: Sprint-era pragmatic decisions presented as deliberate architectural choices
2. **Existence does not equal integration**: "The code runs at boot" conflated with "meaningfully affects user behavior"
3. **Absence of negative evidence**: Not a single methodology described as "uncalibrated" or "of unknown impact"

Confirmed the classifier execution order mismatch: zero-shot runs AFTER embedding, not before. Confirmed the L2 formula uses `1 - d/2` when the correct derivation gives `1 - d²/2`.

### Cost-Benefit Challenge (Avg: 4.6)
**What actually earns its keep** (high ROI): Event-driven write hooks (8/10), Matryoshka truncation (8/10), BFS traversal (7/10), KNN via sqlite-vec, BM25 via FTS5, keyword classification.

**Worst ROI**: Louvain community detection (2/10) — 375 lines + networkx dependency for bridge nodes in 2 commands. Engagement/Brain Level (3/10) — 850 lines, 5 tables, broken column references. Redundant classifier tiers (4/10) — zero-shot and embedding do the same math with different thresholds.

The honest methodology count is ~10 integrated, 2 partially integrated, 1 redundant.

### Alternative Paths (Avg: 3.9)
**Best unexplored path**: LLM-primary architecture. Claude can do classification, scoring, trend analysis, and connection-finding in a single prompt. For a vault of <5000 files, the entire system could be: FTS5 for retrieval + embeddings for similarity + Claude for everything else. This reduces 13 methods to ~4 with equivalent user-perceived quality.

Other unexplored alternatives: trained classifier on accumulated data (replaces 3 tiers), embedding-space interpolation for /connect (replaces community bridge nodes), query-adaptive RRF weights (based on query IDF instead of command type), Personalized PageRank instead of BFS.

### Risk Amplification (Avg: 3.4)
**Top 3 unidentified risks**:
1. **SQLite connection exhaustion**: `embedding_store._get_vec_connection()` creates raw connections bypassing `db_connection.py` lifecycle management. Leaked connections from exception paths accumulate over days of daemon operation until "database is locked" kills all writes.
2. **Silent data corruption from TOCTOU race**: `update_icor_edges_for_file()` deletes then inserts edges in separate connections with no transaction boundary. Concurrent reads between delete and insert see zero edges.
3. **Embedding model memory leak**: sentence-transformers on CPU fragments the heap over thousands of `model.encode()` calls. No memory monitoring, no periodic restart, no launchd memory limit. Process grows from ~800MB to 2-3GB over months.

### User Impact Assessment (Avg: 2.1)
**The devastating finding**: The griller queried the production database.
- 17 total captures in 3 weeks
- 0 search queries logged (search_log empty)
- 0 completed actions
- 8 days of engagement data out of 22 possible
- 4 of 6 life dimensions frozen
- 0 concept promotions

**Verdict**: "Well-built scaffolding around an empty building." The system is optimized for analyzing a rich knowledge base that does not yet exist. The bottleneck is input, not analysis.

## Blind Spots Exposed

These issues were found by only 1-2 lenses:

1. **Column name mismatch in `engage` command SQL** (Risk + Cost-Benefit): Queries reference `consistency, breadth, depth` but table has `consistency_score, breadth_score, depth_score`. The engage command silently fails.
2. **`get_neighbors` BFS is dead code** (Feasibility only): `graph_ops.get_neighbors()` is never called in production — `vault_indexer.get_linked_files()` reimplements a wikilink-only BFS inline.
3. **Thundering herd on first classification** (Risk only): First `_tier_embedding` call after boot loads the model (~5-10s). All 8 concurrent handlers block on `_model_lock`.
4. **Journal mood/energy SQL has no GROUP BY** (Risk only): Multiple entries per date return arbitrary mood/energy values.
5. **Louvain nondeterminism** (Risk only): Community IDs change on every restart. Any cached community_id references query the wrong cluster.

## Alternative Approaches Missed

1. **LLM-primary architecture**: Use Claude for classification, scoring, connection-finding directly. Reduces 13 methods to ~4 (FTS5, embeddings, keyword pre-filter, LLM). Best unexplored path per Agent 5.
2. **Trained classifier on accumulated data**: After a few hundred classified messages, fine-tune a tiny model (SetFit) to replace tiers 2-4 of the cascade.
3. **Embedding-space interpolation for /connect**: Compute midpoint of two domain centroids, retrieve nearest documents. No graph infrastructure needed.

## Confidence Scores

| Decision | Devil | Feasibility | Bias | Cost-Benefit | Alternatives | Risk | User Impact | **Average** |
|----------|-------|-------------|------|-------------|-------------|------|-------------|-------------|
| 1. Two cosine impls | 4 | 6 | 4 | 6 | 4 | 3 | 2 | **4.1** |
| 2. Louvain integration | 4 | 5 | 3 | 2 | 3 | 3 | 1 | **3.0** |
| 3. RRF per-command weights | 5 | 6 | 3 | 5 | 5 | 4 | 2 | **4.3** |
| 4. BFS configurable depth | 5 | 6 | 5 | 7 | 4 | 4 | 5 | **5.1** |
| 5. L2-to-similarity formula | 3 | 5 | 4 | 4 | 3 | 4 | 1 | **3.4** |
| 6. Matryoshka truncation | 6 | 7 | 5 | 8 | 5 | 3 | 1 | **5.0** |
| 7. 5-tier classifier | 4 | 5 | 3 | 4 | 4 | 3 | 3 | **3.7** |
| 8. Engagement/Brain Level | 3 | 4 | 2 | 3 | 3 | 4 | 3 | **3.1** |
| 9. Event-driven pipeline | 4 | 5 | 4 | 8 | 4 | 3 | 2 | **4.3** |
| 10. Community bridge nodes | 3 | 4 | 3 | 2 | 3 | 4 | 1 | **2.9** |
| 11. All 13 integrated | 5 | 7 | 2 | 3 | 3 | 2 | 2 | **3.4** |

## Final Verdict

**Would a staff engineer approve this?**

### APPROVE WITH MAJOR REVISIONS

**What is strong enough to keep:**
- RRF hybrid search (remove per-command weights until data supports them)
- Event-driven vault write hooks (add retry + transaction boundaries)
- BFS graph traversal (keep as-is)
- Matryoshka truncation + sqlite-vec KNN (correct, well-researched)
- BM25 via FTS5 (zero-maintenance, built into SQLite)
- Keyword classification tier (fast, interpretable)

**What must change before proceeding:**
1. **Fix the L2-to-similarity formula**: Change `1 - distance/2` to `1 - distance**2/2` (1-line fix, but rebuild semantic_similarity edges after)
2. **Fix the `engage` command column names**: `consistency` to `consistency_score`, etc.
3. **Fix the classifier `_cosine_similarity` zero-norm guard**: Add the same guard the pure Python version has
4. **Add transaction boundaries** to `update_icor_edges_for_file` (delete + insert in one transaction)
5. **Fix the journal mood/energy GROUP BY** in `compute_daily_metrics`

**What should be reconsidered entirely:**
1. **Louvain community detection**: Remove or defer until vault exceeds 500 files. The networkx dependency, 375 lines of code, and boot-time computation deliver near-zero value at 89 files.
2. **Engagement/Brain Level subsystem**: Either fix the broken SQL and calibrate against real usage data, or remove entirely. The formulas are arbitrary and the system has never been exercised end-to-end.
3. **Zero-shot classifier tier**: Merge with embedding tier (they do identical math at different thresholds). Reduce to 4-tier cascade.
4. **Focus on the real bottleneck**: The user has 17 captures in 3 weeks. The system needs frictionless capture and daily nudges, not more analysis algorithms. Build the content pipeline before optimizing the analysis pipeline.

---
type: reference
date: 2026-03-28
icor_elements: [Systems & Environment, Mind & Growth]
status: evergreen
tags: [graph-memory, architecture, research, rag, knowledge-graph]
---

# Graph Memory Research & Impact Analysis

**Date**: 2026-03-28
**Scope**: Deep research on EdgeQuake, Awesome-GraphMemory, mathematical foundations, and 5 proposed additions to the Second Brain
**Method**: 50+ parallel research agents across 4 phases
**Grill review**: Adversarial review by 7 independent agents (2026-03-28). Key revisions incorporated below.

---

## Table of Contents

1. [Phase 1: DoltHub Evaluation](#phase-1-dolthub-evaluation)
2. [Phase 2: Repository Deep-Dives](#phase-2-repository-deep-dives)
3. [Phase 3: Mathematical Foundations](#phase-3-mathematical-foundations)
4. [Phase 4: Five Proposed Additions](#phase-4-five-proposed-additions)
5. [Revised Implementation Roadmap](#revised-implementation-roadmap)
6. [Cross-Addition Interactions](#cross-addition-interactions)
7. [Grill-Informed Revisions](#grill-informed-revisions)

---

## Phase 1: DoltHub Evaluation

**Verdict: Don't migrate. Stay on SQLite.**

DoltHub/Dolt is a MySQL-compatible database with Git-style version control (branching, merging, diffing, time-travel queries). Evaluated by 3 agents.

**Why it doesn't fit:**
- sqlite-vec (vec0 virtual tables) and FTS5 have no Dolt equivalents — the entire hybrid search pipeline would break
- Dolt requires running a server process (no embedded mode for Python) — pure overhead for a single-user system
- 2-6x slower than MySQL on benchmarks; SQLite is faster for single-user workloads
- Migration would touch every `sqlite3` call, every PRAGMA, every FTS5 query, every vec0 operation — 826 tests at risk

**What Dolt does well (that we don't need):**
- Time-travel queries (`AS OF`) — rarely needed for personal PKM
- Branch/merge for data experiments — `cp brain.db brain-experiment.db` takes milliseconds
- Distributed collaboration — single-user system
- Audit trail via `dolt_history_*` — achievable with SQLite triggers (~20 lines per table)

**Alternatives that give Dolt's benefits on SQLite:**

| Benefit | SQLite Alternative | Effort |
|---|---|---|
| Versioned backups | Litestream to S3 | 1 hour |
| Audit trail | SQLite AFTER UPDATE triggers + `_history` tables | 1 migration step |
| Schema rollback | Add `down()` functions to migrate-db.py | 1 day |
| Experiment branches | `cp brain.db brain-experiment.db` | Already possible |
| Offsite push | Litestream or cron + rclone | 1 hour |

---

## Phase 2: Repository Deep-Dives

### EdgeQuake (`raphaelmansuy/edgequake`)

**What it is**: Rust-based Graph-RAG server (v0.7.0, 1.5k stars, Apache 2.0) implementing the LightRAG algorithm. 11 crates, 130K LOC, 2600+ tests. Uses PostgreSQL + Apache AGE + pgvector.

**Architecture highlights:**
- 6 query modes: Naive, Local, Global, Hybrid, Mix, Bypass
- LLM-powered entity extraction with 7 configurable types + multi-pass gleaning (15-25% recall improvement)
- Community detection (Louvain) for thematic clustering
- SQL pre-filtering before vector scan (90% fewer wasted comparisons)
- 10 language SDKs, MCP server, React 19 frontend with Sigma.js graph visualization

**Verdict: Don't integrate.**

| Factor | Assessment |
|---|---|
| Architecture fit | Server-grade (PG + Docker) vs embedded SQLite. Fundamental mismatch |
| Feature overlap | Our hybrid search (FTS5 + vec + chunks + graph) covers 80% of EdgeQuake's retrieval |
| Unique value | LLM-powered NER (entity extraction). *Grill note: "200-line NER" is underscoped — needs defined entity schema, accuracy metrics, and consumer. More realistic: add `entities` field to existing LLM classification call response schema (zero new infrastructure) as a first step, then evaluate whether a standalone module is justified.* |
| Migration cost | 20-40 hours, doubles operational surface area |
| Who it's for | Teams building multi-tenant document search products. Not single-user PKM |

**Competitive position:**
```
                    Agent Memory <----------> Document Retrieval
                         |                         |
    High Maturity    Mem0 (48k*)             MS GraphRAG (31k*)
                     Graphiti (24k*)         LightRAG (30k*)
                         |                         |
    Low Maturity     Cognee, Letta           EdgeQuake (1.5k*)
```

### Awesome-GraphMemory (`DEEP-PolyU/Awesome-GraphMemory`)

**What it is**: Survey paper companion (arXiv:2602.05665, Feb 2026) cataloging ~100+ papers on graph-based memory for LLM agents. Maintained by Hong Kong PolyU's DEEP Lab.

**Taxonomy: Extraction -> Storage -> Retrieval -> Evolution**

**6 architectural patterns identified:**

| Pattern | Exemplar | Core Idea |
|---|---|---|
| KG as External Memory | MemLLM, AriGraph | LLM reads/writes entity-relation triples |
| Temporal KG | Zep/Graphiti | Bi-temporal edges with validity windows |
| Multi-Graph | MAGMA | Parallel semantic/temporal/causal/entity views |
| Hierarchical (OS-inspired) | MemGPT/Letta | Core -> Recall -> Archival memory tiers |
| Hippocampal | HippoRAG | Schemaless KG + Personalized PageRank |
| Zettelkasten | A-MEM | Self-organizing notes with agentic link generation |

**Key papers:**
- MemGPT (2023): OS analogy for LLM memory — core/recall/archival tiers
- HippoRAG (NeurIPS '24): Schemaless KG + Personalized PageRank, 10-30x cheaper than iterative retrieval
- Microsoft GraphRAG (2024): Community detection + hierarchical summarization for global queries
- Graphiti/Zep (2025): Bi-temporal model, 94.8% accuracy on Deep Memory Retrieval, 90% latency reduction
- MAGMA (Jan 2026): Multi-graph views + dual-stream writes, 45.5% higher reasoning accuracy
- A-MEM (NeurIPS '25): Zettelkasten for agents, self-organizing note links

**What our system already has vs what's missing:**

| Capability | Our System | Gap |
|---|---|---|
| Entity-relation graph | vault_nodes + vault_edges (4 edge types) | No LLM entity extraction from prose |
| Community detection | Louvain via NetworkX | No community summaries cached |
| Hybrid search | 4-channel RRF (vector + chunks + FTS5 + graph) | Equal weights, no intent-aware routing |
| Temporal awareness | `created_at` only | No validity windows, no "as of" queries |
| Memory consolidation | None | No auto-archival, no fading detection |
| Episodic memory | `captures_log` (flat rows) | No session grouping |
| Feedback loop | `keyword_feedback` for classifier | Doesn't feed back into graph weights |

**Verdict: Gold mine of implementable techniques. 5 proposals identified.**

---

## Phase 3: Mathematical Foundations

### I. Retrieval & Ranking

**Cosine Similarity** `cos(A,B) = A.B / (||A|| * ||B||)`
- Scale-invariant similarity for text embeddings
- Our thresholds: 0.32 (zero-shot), 0.28 (embedding), 0.52 (ICOR affinity)
- At d=512, random pairs cluster around cos=0 with StdDev=0.044
- ICOR affinity 0.52 = ~6 standard deviations above random baseline

**BM25** `Sum IDF(q_i) * f(q_i,D)*(k1+1) / (f(q_i,D) + k1*(1-b+b*|D|/avgdl))`
- k1=1.2: 10th mention != 10x signal (saturation)
- b=0.75: normalizes for doc length so daily notes don't dominate short concept files
- IDF = -log P(t) = self-information of term t
- "meditation" in 15/500 docs: IDF=3.48. "the" in 490/500: IDF=0.021. 166x difference

**RRF** `score(d) = Sum 1/(k + rank_i(d))`
- k=60: rank 1 gets 1/61=0.0164, rank 2 gets 1/62=0.0161
- Appearing in 3/4 channels beats being #1 in only 1 channel
- Rank-based (not score-based) — handles heterogeneous scoring functions
- Weakness: correlated channels (vector + chunks both use nomic-embed) get double-vote

**Personalized PageRank** `PPR_s(v) = (1-alpha)*s(v) + alpha*Sum PPR_s(u)/L(u)`
- Spreading activation from query-relevant seed nodes
- Nodes reachable via multiple paths score higher
- 10-30x cheaper than iterative LLM retrieval (HippoRAG)
- Would upgrade our BFS in `get_neighbors()` to weighted ranking

**Beam Search on Graphs**: Maintain top-b candidates, expand, score, prune at each hop
- O(D*b*branching) vs BFS's O(branching^D)
- Think-on-Graph (ICLR '24) uses LLM as scoring function

### II. Community Detection & Graph Structure

**Newman-Girvan Modularity** `Q = (1/2m) * Sum [A_ij - k_i*k_j/(2m)] * delta(c_i,c_j)`
- Measures whether communities have more internal edges than random chance
- Q in [0.3, 0.7] = strong community structure
- Resolution limit: can't detect communities smaller than ~sqrt(2m) edges

**Louvain Algorithm**: Phase 1 (greedy local moves) + Phase 2 (collapse communities). O(n log n).
- Our `community.py` uses NetworkX's Louvain with default resolution gamma=1
- Leiden improvement guarantees connected communities (Louvain can produce disconnected ones)

**Centrality Measures:**
- Betweenness: bridge concepts connecting separate topics (for `/connect`)
- PageRank: authoritative concepts (for context loading priority)
- Clustering coefficient: knowledge density per topic cluster
- Structural holes (Burt): nodes bridging disconnected communities = highest creative value

### III. Embedding & Vector Math

**Matryoshka Representation Learning**: Train embeddings where first d dims are valid d-dim embedding
- nomic-embed-text-v1.5: 768 -> 512 truncation loses only ~1.5% quality, saves 33% storage
- Our `_truncate_vector()` slices + re-normalizes to unit hypersphere

**HNSW**: Multi-layer navigable small-world graph, O(log n) search
- At our scale (~1000 vectors), brute-force KNN takes <1ms — HNSW not needed yet
- sqlite-vec does brute-force; pgvector does true HNSW

**Concentration of Measure**: At d=512, Var[cos(X,Y)] = 1/d = 0.002, StdDev = 0.044
- Explains why our thresholds seem "low" (0.28-0.52)
- Real text embeddings are anisotropic (avg pairwise cos = 0.2-0.5, not ~0)

### IV. Temporal & Decay Models

**Ebbinghaus Forgetting Curve** `R(t) = e^(-t/S)`, S grows on each recall
- S=1 day initially. After 5 recalls with growth factor 2.5: S=39 days, R at day 90 = 46.4%
- Without any access: R approaches 0 rapidly

**Bi-Temporal Model** (Zep/Graphiti): Two time axes — valid_time (when true) and transaction_time (when learned)
- Enables "what did the system believe at T1 about what was true at T2?"
- Allen's interval algebra: 13 possible relations between two time intervals

**Bayesian Surprise** `D_KL(posterior || prior)`: Only store memories that change beliefs
- Shannon surprise: "how unlikely was this event?"
- Bayesian surprise: "how much did this event change my mind?"
- Nemori's Predict-Calibrate cycle: 90% token reduction

### V. NLP & Extraction

**CRF Layer** `P(y|x) = (1/Z) exp(Sum [psi_emit + psi_trans])`
- Transition matrix encodes grammar over label sequences (I-ORG can't follow B-TOOL)
- Modern LLMs replace this with in-context structured generation

**Attention = Soft Graph Traversal**: `A = softmax(QK^T/sqrt(d_k))`
- Self-attention over a sequence IS message passing on a fully-connected graph
- When an LLM processes serialized graph context, attention heads reconstruct graph structure
- GAT extends this: learned content-dependent weights replace uniform neighbor aggregation

**Chunking Bias-Variance Trade-off**: `Error(s) = Bias(s)^2 + Variance(s)`
- Small chunks: high precision, miss context
- Large chunks: preserve context, dilute signal
- Sweet spot: 200-600 tokens (our config: MIN=100w, MAX=600w, overlap=50w)

---

## Phase 4: Five Proposed Additions

Each analyzed by 7 agents: Schema, Code Impact, Search Effects, Jobs/Performance, UX, Cross-Addition Interactions, Risks.

### Addition 1: Fading Content Surfacing (Simplified from Ebbinghaus)

> **Grill revision**: The original proposal used the Ebbinghaus forgetting curve (rote memorization dynamics from 1885). The grill's Devil's Advocate correctly identified this as a **category error** — a legal document from 3 years ago hasn't "decayed," it's simply not currently relevant. Memory strength should be a property of query-node relevance, not a node attribute. The full schema (recall_events table, 5th RRF channel, growth factors) is premature for 52 documents.

**Revised approach**: Simple SQL-based fading detection. No new tables, no decay formula, no RRF integration.

**Implementation** (~20 lines of SQL, no migration):

> **Meta-grill correction**: The original query used `last_modified`, which gets auto-touched by post-write hooks, graduation writes, and Notion sync — making it a measure of system activity, not user engagement. Corrected to use `indexed_at` (set once at file creation) combined with a NOT EXISTS check against recent captures_log and journal_entries references.

```sql
-- Surface files not actively referenced in 30+ days with 3+ graph connections
SELECT n.title, n.indexed_at,
       COUNT(e.id) AS edge_count,
       julianday('now') - julianday(n.indexed_at) AS days_since_created
FROM vault_nodes n
LEFT JOIN vault_edges e ON n.id = e.source_node_id
WHERE n.node_type = 'document'
  AND n.file_path NOT LIKE '%Daily Notes%'
  AND n.file_path NOT LIKE '%Inbox%'
  AND n.file_path NOT LIKE '%Reports%'
  AND NOT EXISTS (
      -- Exclude files referenced in recent journal entries via wikilinks
      SELECT 1 FROM vault_edges re
      JOIN vault_nodes src ON re.source_node_id = src.id
      WHERE re.target_node_id = n.id
        AND re.edge_type = 'wikilink'
        AND src.last_modified >= date('now', '-30 days')
  )
GROUP BY n.id HAVING edge_count >= 3
ORDER BY days_since_created DESC LIMIT 5;
```

**Where it surfaces**: Evening prompt (Mon/Wed/Fri only, skip if no journal today), max 3 items.

**What's deferred until 200+ documents**:
- The full Ebbinghaus model (recall_events, strength_param, growth factors)
- 5th RRF channel integration
- memory_strength column on vault_nodes
- Bootstrap complexity (backfill from file age)

**Key guardrail preserved**: Advisory-only. Never auto-archive. Never suppress from search.

**Effort**: 0.5 days (down from 3)

### Addition 2: Temporal Edge Validity

> **Grill revision**: At 146 edges and 28 days of history, the full temporal edge system (130 LOC + 9-file WHERE clause updates + edge_episodes table + partial unique index rebuild) produces near-zero user-visible value. The Feasibility Auditor estimated 7-10 days realistic (vs 3-4 stated). The grill recommends a minimal timestamp approach now, full temporal layer in 3 months if /trace users request historical queries.

**Phase 1 — Now (minimal, 2 lines)**:
- Add `created_at` default to vault_edges (already exists) — ensure it's always populated
- Add `verified_at TEXT` column to vault_edges — updated on every upsert, tells you "when was this edge last confirmed valid"
- No behavioral change to any existing code

**Phase 2 — At 90+ days of data (if /trace users request history)**:
- Full valid_from/valid_until with partial unique index
- Diff-based rebuild in graph_ops.py (~130 LOC)
- 9 files get `WHERE valid_until IS NULL`
- edge_episodes provenance table
- `/trace` Connection Timeline, `/drift` Cross-Dimensional Connectivity, `/emerge` Emerging Connections

**Stale edge policy** (unchanged — this insight is correct regardless of phase):
- wikilink: content-derived, permanent
- tag_shared: content-derived, permanent
- semantic_similarity: content-based invalidation only, NOT timer-based
- icor_affinity: significance threshold (skip if weight change < 0.05)

**Effort**: Phase 1: 0.5 days. Phase 2: 5-7 days (realistic, per Feasibility Audit)

### Addition 3: Hierarchical Memory Consolidation

**What**: Daily entries -> weekly summaries -> monthly summaries. Context loader uses the right tier per time range.

**Schema** (Migration Step 28):
- memory_summaries table (level, period_start, period_end, summary, key_themes_json, dimensions_json, mood_avg, energy_avg, engagement_avg, vault_node_id)
- memory_summary_sources junction table
- vec_memory virtual table (vec0, float[512]) — NOT a BLOB column on memory_summaries
- UNIQUE(level, period_start)

**Token savings**:

| Command | Current Tokens | Tiered Tokens | Savings |
|---|---|---|---|
| drift (60d) | ~39K | ~5.8K | 85% |
| challenge (90d) | ~58K | ~11K | 81% |
| emerge (30d) | ~19.5K | ~10.5K | 46% |
| today (7d) | ~11K | ~5.3K | 53% |

**LLM cost**: $0.00/year on Gemini free tier. $0.026/year on paid Flash. Negligible.

**Grill-informed design decisions**:
- **Provenance flags required** (Risk Amplifier finding): All LLM-generated summaries MUST have `source: system` in frontmatter and be distinguishable from user-authored content in search. Weight user-authored content higher than system-generated content. This prevents provenance erasure — the most dangerous unidentified risk.
- Use structured extraction (themes/mood_arc/decisions/open_questions), NOT free-form narrative — resists telephone game AND ghost voice degradation
- NEVER substitute summaries for raw data in drift/challenge/emerge (analytical commands need granularity)
- Tier-1 window varies by command: 7 days for drift/schedule, 14 days for emerge/challenge
- Label tiers in LLM prompt: "### Journal Summaries (abbreviated, 8-30 days ago)"
- Quarterly level: defer (premature with 28 days of data)

**Simpler alternative to try first** (grill's Cost-Benefit recommendation):
Before building the full 3-tier pipeline, try the **rolling memo** approach: one Claude call/day producing a 200-token structured memo appended to a single file. Zero schema migration, zero new tables.

> **Meta-grill correction**: The rolling memo WAS rejected in the first revision on "retrievability" grounds ("how do you search a single 6000-token file?"). This was factually wrong — the existing chunking infrastructure (`chunker.py`, `chunk_embedder.py`) was built precisely to make large files retrievable via section-level embeddings. The real reasons to prefer structured weekly summaries over a rolling memo are: (1) each summary gets its own discrete embedding in `vec_vault`, making it a first-class search result rather than a chunk within a growing file; (2) structured extraction fields (themes, mood_arc, decisions) are more query-efficient than searching within a chronological append log; (3) weekly boundary files are natural units for the tiered context loader. The conclusion (prefer structured summaries) may still hold, but the stated reasoning must be honest about why.

**Schedule**: Monday 5:30am (weekly), 2nd of month 5:30am (monthly). Catch-up for missed weeks (max 4).

**Effort**: Rolling memo: 1 day. Full pipeline: 5 days (only if memo proves insufficient)

### Addition 4: Sleep Consolidation for Concept Graduation

**What**: Nightly job clusters uncategorized captures by embedding similarity (DBSCAN), proposes concept notes via Telegram with approve/reject buttons.

**Detection algorithm** (revised per grill):

> **Grill findings**: (1) DBSCAN params (eps=0.35, min_samples=3) are unvalidated "precision theater" — calibrated from theory, not actual vault data. (2) Existing community detection is a free alternative that avoids a new clustering dependency. (3) Missing prerequisite: captures_log rows are embedded via inbox files in vec_vault, but the detection assumes direct capture-to-embedding mapping that doesn't exist cleanly.

**Simplified v1** (use existing infrastructure):
- Use existing Louvain communities + keyword frequency from captures_log to detect recurring themes
- Theme = ICOR element appearing 3+ times across 7+ days in captures with no existing concept note
- This avoids DBSCAN, avoids new dependencies, and leverages the classifier's dimension routing

**Full v2** (if v1 proves insufficient):
- DBSCAN/HDBSCAN on capture embeddings (validate eps against actual vault data, not theory)
- Coherence check: mean pairwise cosine >= 0.60
- Temporal spread: min 2 distinct calendar days (grill says 7 days minimum to prevent hot-topic noise)
- 3-layer dedup: title similarity, embedding cosine >= 0.75, hybrid search overlap

**Telegram approval flow**:
- Posted to brain-insights topic
- Buttons: Approve, Edit Name (ConversationHandler), Reject, Not Now (7-day snooze)
- graduation_proposals table with cluster_hash for idempotency
- 14-day auto-expiry, max 2 proposals/day
- Exponential backoff on unanswered proposals (3 consecutive unanswered -> double interval)

**Vault write pipeline**:
- Uses existing `create_concept_file()` — post-write hooks handle all 8 stages of indexing
- Source captures annotated with `status: graduated, graduated_to: "Concept-Name"` in frontmatter
- No separate `consolidation` edge type needed — wikilinks from Sources section handle provenance

**Graph impact**:
- New concept becomes hub node (degree 5+), may merge communities (usually desirable)
- ICOR affinity computed fresh from concept's own embedding (not inherited from sources)
- No special community detection trigger — next scheduled Louvain run picks it up

**Key risks & mitigations**:
- P0: False graduation -> coherence >= 0.60 + min 2 days + LLM validation with explicit rejection
- P0: Redundant concepts -> 3-layer dedup (title, embedding, search)
- P1: Concept inflation -> hard cap **1/week** (grill strongly endorsed this, not 2/day as originally designed) + seedling lifecycle (30-day review_by, auto-archive if stale)
- P1: User abandonment -> exponential backoff + **batch into weekly review** (grill: don't create a new notification category)
- P1: Human-in-the-loop bottleneck (grill Risk #2) -> 5 new attention-demanding features on top of 7 existing alert types creates a second job. Cap total system notifications.
- P2: Premature graduation -> **7-day minimum spread** (grill upgraded from 2 days) + 3-day cooldown
- P2: DBSCAN approval staleness (grill blind spot) -> cluster computed at 2:30am, user approves at 9am, vault has changed. Revalidate cluster at approval time.

**Performance**: DBSCAN on 50 captures: <1ms. On 500: 50-200ms. No scikit-learn needed (numpy + scipy sufficient).

**Effort**: 4-5 days

### Addition 5: Intent-Aware Retrieval Routing

**What**: Per-command weight profiles for the 4 RRF channels. Weighted RRF: `weight / (k + rank + 1)`.

**Implementation** (~25 lines across 3 files):

```python
_COMMAND_CHANNEL_WEIGHTS = {
    "find":    {},                                      # equal weights
    "trace":   {"graph": 1.5, "chunks": 1.3},          # structure + sections
    "ideas":   {"chunks": 1.4, "fts": 1.2},            # section-level + keywords
    "connect": {"graph": 1.8, "vector": 1.3},          # graph intersections + semantic
}
```

- `_rrf_fuse()`: add `channel_weights` param, apply `weight * 1/(k+rank+1)`
- `hybrid_search()`: add `channel_weights` param, pass to `_rrf_fuse`
- `context_loader.py`: pass weights from `_HYBRID_SEARCH_COMMANDS`

**Weight archetypes** (instead of per-command):

| Archetype | Vector | Chunks | FTS | Graph | Commands |
|---|---|---|---|---|---|
| Semantic | 1.0 | 1.0 | 0.7 | 0.5 | find, ghost, challenge |
| Structural | 0.5 | 0.5 | 0.7 | 1.5 | trace, emerge, graduate |
| Temporal | 0.8 | 0.8 | 1.0 | 0.3 | drift, today, close-day |
| Comprehensive | 1.0 | 1.0 | 1.0 | 1.0 | ideas, projects, resources |

**Community expansion** (post-RRF, not 5th channel):
- `expand_communities(file_paths, max_per_community=3, max_total=6)`
- Skip at current scale (52 nodes) — revisit at 500+
- Community summaries: WAIT until 2000+ nodes. Centroids (mean of member embeddings) are cheaper and nearly as good

**Quality measurement**:
- Deploy search_log table + shadow scoring first (log both weighted and unweighted rankings)
- Canary queries (3-5 known good results) catch regressions
- Wait 4+ weeks of log data before switching to weighted
- At 52 docs, channels barely disagree — weighted routing has marginal impact

**Key risks**:
- Minimum weight floor 0.05 (never fully silence a channel)
- Unify `/find` dual FTS path before adding weights (FTS results currently bypass hybrid search)
- Community expansion needs relevance re-ranking (ICOR-based isolate assignment makes communities heterogeneous)

**Effort**: 2 days

---

## Revised Implementation Roadmap

> **Grill revision**: The original order (FC -> IR -> TE -> HC -> CG) was ordered by mathematical elegance, not user value. The grill's User Impact Skeptic scored Concept Graduation at 7/10 and everything else at 1-4/10. The highest-impact feature shipped last. Inverted per the grill's strongest recommendation.

### Week 1: Concept Graduation (highest user impact: 7/10) + Measurement Infrastructure

> **Meta-grill risk acknowledgment**: CG is the highest-impact feature AND the highest-risk feature to ship first. Each graduation fires the full 8-step post-write hook chain (5 async operations). Add a circuit breaker: max 3 vault writes per graduation run, with a 2-second delay between writes to prevent WAL contention.

- **Concept Graduation v1**: Use existing community detection + keyword frequency (no DBSCAN). graduation_proposals table. Telegram approval flow (Approve/Edit/Reject/Snooze). Hard cap 1/week. Batch into weekly review. **Circuit breaker**: max 3 concept files per run.
- **search_log table**: 1-day investment for measurement infrastructure (IR agent's highest-ROI recommendation). Log all search queries, per-channel rankings, and final RRF results. **Prerequisite**: Set `LANGFUSE_ENABLED=true` before sprint starts.
- **Provenance flag**: Add `source: system` to all bot-generated vault file frontmatter AND verify read-side filtering in `ghost`/`challenge` command presets. Check whether existing `type: report` filter already suffices before adding a new field.

### Week 2: Simple Fading + Rolling Memo (test the simpler alternatives first)
- **Fading Content Surfacing**: 20-line SQL query in evening prompt (Mon/Wed/Fri). No new tables, no Ebbinghaus formula.
- **Rolling Memo**: One Claude call/day, 200-token structured append to a single file. Test whether this provides enough context compression before building the full 3-tier pipeline.
- **verified_at column**: Add to vault_edges (2 lines). Updated on every upsert. Minimal temporal awareness.

### Week 3: Evaluate and decide (with pre-committed kill criteria)

> **Meta-grill correction**: The original gate had no defined success criteria, making it "a scheduled self-affirmation rather than a genuine decision point." Kill criteria must be defined NOW, before Week 1 sunk costs create bias. Enable `LANGFUSE_ENABLED=true` before the sprint starts.

**Kill criteria (defined before implementation begins):**

| Feature | Continue if... | Kill/Pause if... |
|---|---|---|
| Concept Graduation | >= 2 of 4 proposals accepted by user in 3 weeks | 0 of 4 proposals accepted, OR user snoozes/ignores all |
| Fading Surfacing | User taps "Review" on >= 1 fading item in 2 weeks | User never interacts with fading section after 3 weeks |
| Rolling Memo | Context loader actually loads memo content in >= 5 commands | Memo file grows but is never retrieved by any command |
| search_log | >= 50 logged queries with channel ranking data | Logging fails silently or produces corrupt data |
| verified_at | Column populated on >= 80% of edge upserts | Post-write hooks skip the update due to threading issues |

- Review search_log data (4 weeks accumulated). Do channels disagree enough to justify weighted routing?
- Review rolling memo quality. Does it reduce context tokens meaningfully? Is the telephone game a problem?
- Review graduation proposals. Did v1 detection (community + keywords) produce good candidates?
- **Each metric above determines its feature's fate independently.** Not a single go/no-go for everything.

### Week 4+ (only if data justifies):
- **Intent-Aware Routing**: Deploy weighted RRF if search_log shows channels disagreeing meaningfully
- **Full Temporal Edges**: Build if /trace users request historical queries and 90+ days of edge data exists
- **Full Hierarchical Consolidation**: Build 3-tier pipeline if rolling memo proves insufficient
- **Concept Graduation v2**: Switch to DBSCAN/HDBSCAN if community-based detection misses clusters

### Total: ~8 days for Weeks 1-2 (down from 18). Week 3 is evaluation, not building. Week 4+ is conditional.

---

## Cross-Addition Interactions

### The "Knowledge Metabolism" (all 5 active)
1. Raw captures arrive (existing)
2. CG clusters and graduates them into concepts (creation)
3. TE timestamps the connections (temporal context)
4. FC assigns memory strength and schedules review (spaced repetition)
5. HC consolidates concepts into summaries (aggregation)
6. IR routes future queries efficiently (retrieval)
7. FC decays unused concepts (forgetting)
8. CG notices re-mentioned decayed concept -> re-graduates (rebirth)

### Dependency Map
```
CG (Graduation) -----> TE (Temporal Edges) -----> FC (Forgetting Curve)
       |                       |                          |
       v                       v                          v
HC (Consolidation) <--- reads TE edges         IR (Routing) <--- uses FC strength
       |                                              |
       v                                              v
  Weekly summaries reference graduated concepts    Weighted search uses all signals
```

### Key Interactions
- FC + CG: Graduation is a recall event (boosts strength). Apply 0.3x absorption penalty on source captures.
- FC + IR: Negative weight for emerge/challenge (surface forgotten material)
- TE + HC: Weekly consolidation queries "edges valid during this week"
- CG + HC: Exclude vault/Reports/ from clustering input (prevent circular dependency)
- FC + HC: Summary nodes exempt from decay (infrastructure, not user content)
- TE + Community: Run community detection AFTER edge pruning

### Scheduled Job Order (Revised)

> **Grill revision**: Wall-clock scheduling creates collision risk when jobs overrun (PTB JobQueue has no dependency chains). For Week 1-2 additions, only Concept Graduation adds a nightly job. The full 9-job chain is deferred.

**Week 1-2 schedule** (minimal additions to existing chain):
```
4:00am  DB Backup (existing)
5:00am  Vault Reindex (existing)
5:15am  Concept Graduation (weekly, Sundays — after fresh embeddings)
5:30am  Daily Engagement (existing)
5:45am  Dimension Signals (existing)
6:00am  Dashboard Refresh (existing)
7:00am  Morning Briefing (existing)
```

**Future full chain** (only if Week 3 evaluation gate passes):
- Add dependency-chain scheduling (each job triggers next on completion) before adding more nightly jobs
- Add a mutex to prevent parallel SQLite writes during the maintenance window

---

## Grill-Informed Revisions

> The 3-tier profile system (conservative/balanced/aggressive) has been **removed** per the grill's Cost-Benefit Challenger (scored 2/10). It was premature abstraction for a single-user tool that conflated independent parameters under a single dial (a user wanting aggressive graduation but conservative decay could not express that).

**Replacement**: Hard-code one set of well-commented defaults. Add configurability only when a user actually requests it. Each feature gets its own clearly documented constants in its own module, not a centralized profile system.

### Key Revisions from Grill Report (with meta-grill corrections)

> **Meta-grill pattern**: The first revision round exhibited "acceptance without consequence" — critiques were praised but produced no specific code change. This table now lists the **concrete code-level action** for each revision.

| Original Decision | Grill Challenge | Revision | **Concrete Action** |
|---|---|---|---|
| Implementation order: FC first, CG last | User Impact: CG=7/10, FC=2/10 | **Inverted**: CG ships Week 1 | `handlers/graduation.py` (new), `graduation_proposals` table, weekly Sunday 5:15am job. Max 3 writes per run (circuit breaker). |
| Ebbinghaus forgetting curve | Category error: rote memorization != knowledge relevance | **Simplified**: SQL-based fading | 20-line SQL in `job_evening_prompt()` in `scheduled.py`. Uses `indexed_at` + NOT EXISTS on recent wikilink edges (not `last_modified`). |
| Temporal edges (130 LOC) | 28-day graph has no history to query | **Phased**: `verified_at` now | `ALTER TABLE vault_edges ADD COLUMN verified_at TEXT;` + one line in `upsert_edge()`: `verified_at = datetime('now')`. |
| 3-tier profiles | Premature abstraction | **Killed** | Delete the profile dict. Each module's constants are inline with comments. |
| Hierarchical consolidation | Token savings achievable with simpler retrieval | **Try rolling memo first** | New daily job appending to `vault/Reports/rolling-memo.md`. Chunker handles retrieval. If discrete summaries prove better (meta-grill: honest reasons are embedding isolation + structured fields, NOT retrievability), build the pipeline. |
| DBSCAN for graduation | Unvalidated params | **v1: community + keywords** | Query `captures_log` for ICOR elements appearing 3+ times across 7+ days with no matching concept in `concept_metadata`. Zero new clustering deps. |
| 18-day total effort | 13/18 days negligible user impact | **8 days + evaluation gate** | Gate has pre-committed kill criteria per feature (see Week 3 table). Enable `LANGFUSE_ENABLED=true` before sprint. |
| Provenance flag (write-only) | Meta-grill: write-only flag = false closure | **Write + read integration** | `source: system` in frontmatter AND `search_filters.py` preset excludes system-source from `ghost`/`challenge`. Verify `type: report` filter first. |

### Critical Blind Spots Added

1. **Provenance erasure**: All LLM-generated vault files now require `source: system` frontmatter. **Read-side integration required** (meta-grill correction: a write-only flag creates false closure):
   - `search_filters.py`: Add `exclude_system_source=True` default for `ghost` and `challenge` command presets (these commands must only use user-authored content)
   - `context_loader.py`: Identity-sensitive commands (`ghost`, `challenge`) filter `WHERE type NOT IN ('report', 'weekly_summary', 'monthly_summary')` in vault file loading
   - **Note**: `type: report` already exists on bot-generated files via `create_report_file()` — verify this is already filtered in identity-sensitive commands before adding a new field. If `type: report` suffices, `source: system` may be redundant.

2. **Human-in-the-loop bottleneck**: 5 new attention-demanding features + 7 existing alert types = cognitive overload risk. Cap total system notifications. Batch graduation proposals into weekly review instead of creating a new notification category.

3. **Nightly job chain contention**: 9+ jobs writing to same SQLite file between 2:30am-7:00am. Add dependency-chain scheduling (each job triggers next on completion) rather than wall-clock scheduling.

4. **Capture-time schema enforcement** (grill's best unexplored alternative): Instead of 5 post-hoc systems to compensate for unstructured input, consider adding a Telegram quick-reply keyboard for dimension + intent tagging at capture time. Root-cause fix in 2-3 days vs symptom-treatment in 18 days.
   > **Meta-grill correction on the first revision's rejection**: The rejection invoked "frictionless capture" as a design axiom to dismiss this entirely. The meta-grill's Bias Detector flagged this as "principle laundering" — using your own axiom to reject external criticism is circular. The Alternative Path Explorer's better framing: **enforce at evening `/close` review, not at capture time**. This preserves frictionless capture while ensuring quality. The user reviews the day's captures once (already happens in `/close`), tags any that were misclassified, and the system learns. This is not the grill's original proposal but addresses the underlying concern without friction.

5. **Silent correctness failure**: No ground-truth validation loop exists. 826 tests check "does it run?" but zero tests check "is the output correct over time?" Add integration tests for cross-addition interactions before shipping.

6. **Cost-Benefit discipline** (meta-grill correction): The first revision dismissed the grill's Cost-Benefit Challenger as "optimizing for the null hypothesis." The meta-grill correctly identified this as an ad hominem dismissal (3.6 avg score). The Challenger's actual argument was substantive: **the author systematically accepts critiques that reduce complexity and rejects critiques that would require abandoning design commitments.** The proper response is not to dismiss the lens but to engage with its specific ROI arguments: (a) Temporal Edges Phase 1 costs 0.5 days for a column nobody reads yet — is that justified? Yes, because the column begins accumulating data passively. (b) Rolling memo costs 1 day — is that justified vs doing nothing? Yes, only if the daily append is actually loaded by context_loader; add a usage counter. (c) Fading surfacing costs 0.5 days — is that justified? Yes, minimal cost and directly user-visible in evening prompt.

7. **The bot has no accumulating user model** (meta-grill User Impact finding): "The author is thinking about graph features when the user's actual experience is 'the bot doesn't know me yet.'" Every session starts from scratch. This is the real user experience gap — not fading content or temporal edges. The `/brain:context-load` command exists but isn't automatic. Consider: should Concept Graduation proposals include a "here's what I know about you" preamble built from graduated concepts? This would make the knowledge metabolism user-visible.

---

## References

### Repos Analyzed
- [raphaelmansuy/edgequake](https://github.com/raphaelmansuy/edgequake) — Rust Graph-RAG server
- [DEEP-PolyU/Awesome-GraphMemory](https://github.com/DEEP-PolyU/Awesome-GraphMemory) — Graph memory survey

### Key Papers
- Graphiti/Zep: Temporal KG Architecture (arXiv:2501.13956)
- MAGMA: Multi-Graph Agentic Memory (arXiv:2601.03236)
- A-MEM: Agentic Memory for LLM Agents (arXiv:2502.12110, NeurIPS '25)
- MemoryBank: Ebbinghaus for LLMs (AAAI '24)
- HippoRAG: Hippocampal Indexing (NeurIPS '24)
- Microsoft GraphRAG: Community Summarization (arXiv:2404.16130)
- Think-on-Graph: Beam Search on KGs (ICLR '24)
- Nemori: Free Energy Principle for Memory (arXiv:2508.03341)
- Memory-R1: RL for Memory Management (arXiv:2508.19828)
- Mem0: Production Agent Memory (arXiv:2504.19413)

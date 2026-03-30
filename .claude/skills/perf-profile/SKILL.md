---
name: perf-profile
description: >
  Use this skill when the application is slow and you need to find the bottleneck,
  memory usage is growing over time in the bot daemon, SQLite queries are taking
  too long, embedding generation needs optimization, or you want to establish
  performance baselines before and after changes. This covers CPU profiling with
  py-spy and cProfile, memory profiling with tracemalloc and scalene, SQLite query
  analysis with EXPLAIN QUERY PLAN, bot daemon memory leak detection, and
  before/after measurement discipline. Always measures first, then optimizes, then
  verifies improvement. Distinguished from pr-review (which flags performance risks
  in a diff but does not run profilers) and from dep-audit (which analyzes
  dependency bloat but not runtime performance).
---

# Performance Profiler

Systematic performance profiling for the Second Brain Python application. Identifies CPU, memory, and I/O bottlenecks. Always measures before and after.

## Golden Rule: Measure First

Never optimize without profiling first. Establish a baseline, identify the bottleneck, fix it, then verify the improvement.

## Steps

### 1. Establish Baseline

Record current metrics before touching anything:

```bash
# Quick project scan for performance risk indicators
python3 .claude/skills/perf-profile/scripts/performance_profiler.py ./file://scripts/brain-bot/

# Measure test suite speed
time cd ./file://scripts/brain-bot && python -m pytest --tb=no -q 2>/dev/null

# Check bot process memory
ps -o rss,vsz,pid -p $(pgrep -f "app.py") 2>/dev/null
```

### 2. Identify the Bottleneck

Choose the right tool based on the symptom:

| Symptom | Tool | Command |
|---------|------|---------|
| Slow overall | py-spy | `py-spy top --pid $(pgrep -f app.py)` |
| Slow function | cProfile | `python -m cProfile -s cumtime script.py` |
| Memory growth | tracemalloc | See recipes below |
| Slow query | EXPLAIN | `sqlite3 data/brain.db "EXPLAIN QUERY PLAN ..."` |
| Embedding slow | time | `time python -c "from core.embedding_store import ..."` |

### 3. Profile

#### CPU Profiling (Python)
```bash
# Live top-like view of running bot
py-spy top --pid $(pgrep -f "app.py")

# Record flamegraph
py-spy record -o profile.svg --pid $(pgrep -f "app.py") --duration 30

# Profile a specific script
python -m cProfile -s cumtime ./file://scripts/brain-bot/core/vault_indexer.py 2>&1 | head -30
```

#### Memory Profiling
```bash
# Quick RSS check over time
while true; do ps -o rss -p $(pgrep -f "app.py") | tail -1; sleep 60; done
```

```python
# tracemalloc snapshot (add to code temporarily)
import tracemalloc
tracemalloc.start()
# ... run your code ...
snapshot = tracemalloc.take_snapshot()
for stat in snapshot.statistics('lineno')[:10]:
    print(stat)
```

#### SQLite Query Profiling
```sql
-- Check query plan (look for SCAN TABLE = bad, SEARCH = good)
EXPLAIN QUERY PLAN
SELECT * FROM vault_nodes WHERE type = 'daily' ORDER BY last_modified DESC LIMIT 10;

-- Check indexes exist
.indices vault_nodes
.indices vault_edges
.indices vault_chunks

-- Time a query
.timer on
SELECT count(*) FROM vec_vault_chunks WHERE embedding MATCH ? AND k = 10;
```

#### Embedding Performance
```bash
# Time embedding generation for a single file
time python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
m.encode(['test document'], convert_to_numpy=True)
print('Model loaded and encoded')
"

# Count files to embed
sqlite3 data/brain.db "SELECT count(*) FROM vault_nodes WHERE node_type='document';"
```

### 4. Analyze Results

- **Flamegraph**: Wide bars = hot functions. Look for unexpected time in I/O or serialization.
- **EXPLAIN QUERY PLAN**: `SCAN TABLE` means no index hit. Add an index.
- **RSS growth**: Steady growth over hours = memory leak. Check embedding model lifecycle.
- **tracemalloc**: Top allocators show where memory is being consumed.

### 5. Apply Fix

One change at a time. Never batch multiple optimizations — you won't know which one helped.

### 6. Verify Improvement

Re-run the same measurement from Step 1. Compare before/after.

### 7. Document the Win

```markdown
## Performance Optimization: [What You Fixed]

**Date:** YYYY-MM-DD

### Problem
[What was slow, how was it observed]

### Root Cause
[What the profiler revealed]

### Baseline (Before)
| Metric | Value |
|--------|-------|
| [metric] | [value] |

### Fix Applied
[What changed]

### After
| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| [metric] | [old] | [new] | [%] |
```

## Quick Wins Checklist

```
SQLite
- Missing indexes on WHERE/ORDER BY columns
- N+1 queries (DB calls in loops in context_loader.py)
- SELECT * when only 2-3 columns needed
- No LIMIT on unbounded queries
- Missing WAL mode (should be set via db_connection.py)

Python Bot
- Embedding model loaded once at boot (not per-request)
- sentence_transformers.encode() uses batching
- No sync I/O in async handlers (use async_utils.py)
- Graph cache used for repeated vault traversals
- Connection pool reused (not new connection per query)

Search Pipeline
- RRF fusion doesn't recompute embeddings unnecessarily
- Metadata filters applied BEFORE vector search (CTE pre-filtering)
- FTS5 queries use proper tokenization
- Chunk embeddings cached (content-hash dedup)
```

## Bot Daemon Memory Leak Detection

The brain-bot runs as a long-lived daemon via launchd. Watch for:

- **RSS growth**: Check hourly with `ps -o rss -p $(pgrep -f app.py)`
- **Embedding model**: SentenceTransformer should be loaded once, not per-request
- **SQLite connections**: Verify centralized connection pooling via db_connection.py
- **Thread pool**: ThreadPoolExecutor should have max_workers set (not unbounded)
- **Graph cache**: `graph_cache.py` should evict stale entries

## Common Pitfalls

- **Optimizing without measuring** — you'll optimize the wrong thing
- **Testing with small data** — 10 vault files vs 1000 reveals different bottlenecks
- **Ignoring the daemon lifecycle** — memory leaks only show after hours of running
- **Premature optimization** — fix correctness first, then performance
- **Not re-measuring** — always verify the fix actually improved things

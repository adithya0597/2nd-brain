# Implementation Plan: Fix Graph Infrastructure + Bot Errors

## Current State

### Graph Issues
| Component | Expected | Actual | Root Cause |
|---|---|---|---|
| Edge types | 4 | 2 (wikilink + icor_affinity) | `semantic_similarity` + `tag_shared` builders never ran |
| Chunks | 65+ | 0 | chunk_embedder not triggered or wiped by migration |
| Vec embeddings | populated | vec0 loads in Python but bot may not load extension | Extension loading may be env-dependent |
| Total edges | 293 | 146 | Missing 2 edge types |

### Bot Errors (from logs)
| Error | Frequency | Severity | Root Cause |
|---|---|---|---|
| **Dashboard: `int(None)` TypeError** | Every 6am/6pm | P0 | `n.get('days_since', 0)` returns None not 0 |
| **Rolling memo: `NoneType.messages`** | Every 9:30pm | P0 | `get_ai_client()` returning None — ANTHROPIC_API_KEY not set or client init failed |
| **Notion sync: API token invalid** | Every 10pm sync | P1 | NOTION_TOKEN expired or wrong |
| **Network errors (7x)** | Intermittent | P2 | WiFi/connectivity drops, no retry handler |
| **Pending captures: SQL error** | Intermittent | P1 | Query against missing table or bad SQL |
| **Missed scheduled jobs** | 3 instances | P2 | Bot was blocked by network errors, missed cron windows |
| **No error handlers registered** | 7x | P1 | PTB app has no global error handler |

---

## Phase 1: Fix Bot Errors (P0 — breaks daily operation)

### 1a. Dashboard `int(None)` crash
**File:** `scripts/brain-bot/handlers/scheduled.py` (~line 254-256)
**Bug:** `int(n.get('days_since', 0))` — when `days_since` is NULL in DB, `.get()` returns the value (None), not the default (0)
**Fix:** Change to `int(n.get('days_since') or 0)`
**Test:** Verify dashboard_refresh runs without error
**Time:** 5 min

### 1b. Rolling memo `NoneType.messages` crash
**File:** `scripts/brain-bot/handlers/scheduled.py` (~line 644 → 111)
**Bug:** `get_ai_client()` returns None — either ANTHROPIC_API_KEY not in env or client init fails silently
**Fix:**
1. Check `.env` has ANTHROPIC_API_KEY set
2. Add guard in `_call_claude()`: `if ai is None: raise RuntimeError("AI client not initialized")`
3. Check `core/ai_client.py` — does `get_ai_client()` handle missing key gracefully?
**Test:** Run `/rolling-memo` manually
**Time:** 15 min

### 1c. Add global PTB error handler
**File:** `scripts/brain-bot/app.py`
**Bug:** "No error handlers are registered" — 7 occurrences. Network errors crash noisily instead of being caught
**Fix:** Add `application.add_error_handler(error_handler)` that logs errors and continues
```python
async def error_handler(update, context):
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
```
**Test:** Verify no more "No error handlers" warnings
**Time:** 10 min

---

## Phase 2: Fix Notion Sync (P1)

### 2a. Rotate/verify Notion token
**Bug:** "API token is invalid" — 14 occurrences
**Fix:**
1. Check `.env` for NOTION_TOKEN — is it set? Is it the right workspace?
2. Test: `python3 -c "from notion_client import Client; c = Client(auth='TOKEN'); print(c.users.me())"`
3. If expired: regenerate at https://www.notion.so/my-integrations and update `.env`
**Time:** 10 min

### 2b. Fix pending captures SQL error
**File:** `scripts/brain-bot/handlers/scheduled.py` (~line 604)
**Bug:** `db_ops.query()` fails — likely querying a table that doesn't exist or column mismatch
**Fix:** Check the SQL query in `job_resolve_pending_captures`, verify table schema matches
**Time:** 15 min

---

## Phase 3: Rebuild Graph Infrastructure (P1 — required for content claims)

### 3a. Rebuild chunks
**File:** `scripts/brain-bot/core/chunk_embedder.py`
**Status:** 0 chunks in DB — need to re-chunk all vault files
**Fix:**
```python
# Run from bot directory
python3 -c "
from core.chunker import chunk_file
from core.chunk_embedder import embed_all_chunks
from core.db_connection import get_connection
import glob

# First chunk all files
conn = get_connection()
for f in glob.glob('../../vault/**/*.md', recursive=True):
    chunk_file(f, conn)
conn.close()
print('Chunking complete')
"
```
**Verify:** `sqlite3 data/brain.db "SELECT count(*) FROM vault_chunks;"` should be > 0
**Time:** 15 min

### 3b. Rebuild semantic_similarity edges
**File:** `scripts/brain-bot/core/graph_ops.py` — `rebuild_semantic_similarity_edges()`
**Status:** 0 edges of this type
**Fix:**
```python
python3 -c "
from core.graph_ops import rebuild_semantic_similarity_edges
from core.db_connection import get_connection
conn = get_connection()
rebuild_semantic_similarity_edges(conn)
conn.close()
print('Semantic similarity edges built')
"
```
**Dependency:** Requires vec0 extension loading + embeddings populated in vec_vault
**Verify:** `sqlite3 data/brain.db "SELECT count(*) FROM vault_edges WHERE edge_type='semantic_similarity';"`
**Time:** 10 min

### 3c. Rebuild tag_shared edges
**File:** `scripts/brain-bot/core/graph_ops.py` — `rebuild_tag_shared_edges()`
**Status:** 0 edges of this type
**Fix:**
```python
python3 -c "
from core.graph_ops import rebuild_tag_shared_edges
from core.db_connection import get_connection
conn = get_connection()
rebuild_tag_shared_edges(conn)
conn.close()
print('Tag shared edges built')
"
```
**Verify:** `sqlite3 data/brain.db "SELECT count(*) FROM vault_edges WHERE edge_type='tag_shared';"`
**Time:** 5 min

### 3d. Re-embed all vault files
**File:** `scripts/brain-bot/core/embedding_store.py`
**Status:** vec0 loads in Python but embeddings may be empty
**Fix:**
```python
python3 -c "
from core.embedding_store import embed_all_files
embed_all_files()
print('All files embedded')
"
```
**Dependency:** sentence-transformers + nomic-embed model must be loadable
**Verify:** Check vec_vault has rows (may need sqlite-vec extension loaded to query)
**Time:** 5-10 min (model loading + embedding)

### 3e. Rerun community detection
**File:** `scripts/brain-bot/core/community.py`
**Status:** 5 communities exist but may be stale after edge rebuild
**Fix:**
```python
python3 -c "
from core.community import update_community_ids
from core.db_connection import get_connection
conn = get_connection()
update_community_ids(conn)
conn.close()
print('Communities updated')
"
```
**Verify:** `sqlite3 data/brain.db "SELECT community_id, count(*) FROM vault_nodes WHERE community_id IS NOT NULL GROUP BY community_id;"`
**Time:** 5 min

---

## Phase 4: Fix Boot Sequence (P1 — prevent recurrence)

### 4a. Verify boot sequence runs all builders
**File:** `scripts/brain-bot/app.py`
**Check:** Does the startup code call:
1. `embed_all_files()` or `embed_missing_files()`
2. `rebuild_semantic_similarity_edges()`
3. `rebuild_tag_shared_edges()`
4. `ensure_icor_nodes()` + `rebuild_all_icor_edges()`
5. `update_community_ids()`
6. `chunk_all_files()` or equivalent

If any are missing, add them to the boot sequence.
**Time:** 20 min

### 4b. Add error handler for vec0 extension loading
**File:** `scripts/brain-bot/core/embedding_store.py`
**Check:** Does the module gracefully handle vec0 not being available?
**Fix:** Add try/except around `sqlite_vec.load(conn)` with clear error message
**Time:** 10 min

---

## Phase 5: Network Resilience (P2)

### 5a. Add retry logic for Telegram network errors
**File:** `scripts/brain-bot/app.py`
**Bug:** 7 `NetworkError` exceptions from httpx — WiFi drops cause unhandled crashes
**Fix:** The global error handler from Phase 1c will catch these. Additionally, PTB v21 supports `connect_timeout`, `read_timeout`, `write_timeout` in `ApplicationBuilder`:
```python
application = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .build()
)
```
**Time:** 5 min

---

## Phase 6: Verify & Update Content

### 6a. Verify all graph numbers after rebuild
```bash
echo "=== EDGES ===" && sqlite3 data/brain.db "SELECT edge_type, count(*) FROM vault_edges GROUP BY edge_type;"
echo "=== NODES ===" && sqlite3 data/brain.db "SELECT node_type, count(*) FROM vault_nodes GROUP BY node_type;"
echo "=== CHUNKS ===" && sqlite3 data/brain.db "SELECT count(*) FROM vault_chunks;"
echo "=== COMMUNITIES ===" && sqlite3 data/brain.db "SELECT community_id, count(*) FROM vault_nodes WHERE community_id IS NOT NULL GROUP BY community_id;"
```

### 6b. Update LinkedIn post with real numbers
After rebuilds, update `content/linkedin-post-part2.md` with actual edge count, node count, and relationship type count.

### 6c. Update Medium article with real numbers
Same for `content/medium-article.md`.

---

## Execution Order

```
Phase 1a  Dashboard int(None) fix              5 min   ← fixes daily 6am crash
Phase 1b  Rolling memo AI client fix           15 min   ← fixes daily 9:30pm crash
Phase 1c  Global error handler                 10 min   ← stops noisy log spam
Phase 2a  Notion token check/rotate            10 min   ← fixes sync failures
Phase 2b  Pending captures SQL fix             15 min
Phase 3d  Re-embed all vault files             10 min   ← prerequisite for 3b
Phase 3a  Rebuild chunks                       15 min
Phase 3b  Rebuild semantic_similarity edges    10 min   ← needs embeddings
Phase 3c  Rebuild tag_shared edges              5 min
Phase 3e  Rerun community detection             5 min   ← after all edges rebuilt
Phase 4a  Verify boot sequence                 20 min   ← prevent recurrence
Phase 4b  Vec0 error handling                  10 min
Phase 5a  Network timeouts                      5 min
Phase 6   Verify numbers + update content      15 min
                                         Total: ~2.5 hours
```

## Success Criteria

- [ ] Dashboard refresh runs at 6am/6pm without crash
- [ ] Rolling memo runs at 9:30pm without crash
- [ ] No "No error handlers" in logs
- [ ] Notion sync succeeds (or gracefully skips with clear error)
- [ ] All 4 edge types populated: wikilink, icor_affinity, semantic_similarity, tag_shared
- [ ] Chunks > 0 in vault_chunks table
- [ ] Communities recalculated after edge rebuild
- [ ] Bot starts cleanly with all builders in boot sequence
- [ ] Content numbers match verified database state

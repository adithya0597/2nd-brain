---
type: project
status: active
date: 2026-04-03
tags: [architecture, knowledge-pipeline, capture, compile, second-brain]
---

# Knowledge Pipeline Architecture

**Purpose**: Comprehensive architecture for evolving the Second Brain from a filing cabinet to a thinking partner. Synthesizes findings from Karpathy's self-improving wiki, two adversarial grill reports, live system data, and the conversation-corpus reframe.

**Status**: Foundation shipped (capture gate fix). Next: 90-minute path, then conversation distiller.

---

## Part 1: What We Learned

### The System Today

| Metric | Count | Source |
|---|---|---|
| Telegram captures | 22 | `captures_log` |
| Action items | 10 | `action_items` |
| Vault files | 129 | `vault/` |
| Graph nodes | 104 | `vault_nodes` |
| Graph edges | 289 | `vault_edges` |
| Reports generated | 31 | `vault/Reports/` |
| Claude sessions | 50 | `.claude/projects/` |
| Session transcript volume | ~2M words (167 MB) | JSONL files |
| Daily notes | 17 | `vault/Daily Notes/` |
| Concept notes | 0 | `vault/Concepts/` |

The grill agents saw 22 captures and called everything premature. They missed 2 million words of unindexed knowledge in Claude conversations. The real corpus is massive. It's just trapped.

### Two Grill Reports, One Convergent Finding

**Grill #1 (2026-04-02)**: Conversation import proposal. Score: 2.5/10. REJECTED. "Bulk-importing raw transcripts degrades search, pollutes the graph, delays P0." Winner: **post-session conversation distiller** (3-5 atomic notes per session, routed through capture pipeline).

**Grill #2 (2026-04-03)**: 3-layer pipeline proposal. Score: 3.7/10. APPROVE WITH MAJOR REVISIONS. "Kill compile job, ship unlinked captures, persist ExtractionResult." Winner: **90-minute path** (add intent/project/due_date to captures_log, wire into /today).

Both grills converge on the same principle: **extract structured artifacts, not raw data. Route through existing pipelines, not new layers.**

### Karpathy's Self-Improving Wiki (What Applies, What Doesn't)

Andrej Karpathy's approach: raw inputs --> LLM compile --> indexed .md wiki --> Q&A --> outputs filed back as new inputs. The feedback loop is the innovation, not the compile step.

| Karpathy Pattern | Applies Here? | Why / Why Not |
|---|---|---|
| Raw capture without friction | Yes | Already works (Telegram inbox, gate fix shipped) |
| LLM extraction at capture time | Yes | Intent extractor already runs, just not persisted |
| Compile raw into structured wiki | Not yet | 129 vault files, 0 concepts. Need 500+ files before this earns its cost |
| Feedback loop (outputs become inputs) | Yes, partially | `/graduate`, `/emerge` exist but run rarely. Distiller closes the loop |
| Q&A over compiled knowledge | Yes | `/find`, `/ghost`, `/trace` already do this |
| Self-improving via corrections | Yes, partially | `keyword_feedback` table exists but only feeds keyword tier, not embeddings |

**Key insight**: The feedback loop already exists in pieces. The gap is not a new compile layer. The gap is:
1. Extraction results are discarded after confirmation UI (not persisted)
2. Classifier corrections don't feed back into embedding or zero-shot tiers
3. Claude conversations (the richest knowledge source) are completely unindexed

---

## Part 2: Safety Infrastructure (Build First)

Every griller flagged these risks. They apply regardless of which features ship. Build them before any automated vault writes.

### 2.1 Vault Backup Before Automated Writes

**Risk**: Any automated vault write (compile job, distiller, auto-linking) could corrupt files. No undo mechanism exists.

**Implementation**:
```python
# In vault_ops.py or a new core/vault_safety.py
import subprocess

def snapshot_vault_before_batch(label: str) -> str:
    """Git commit vault state before batch operations."""
    result = subprocess.run(
        ["git", "add", "vault/"],
        cwd=str(config.PROJECT_ROOT),
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "commit", "-m", f"auto: pre-{label} snapshot",
         "--allow-empty"],
        cwd=str(config.PROJECT_ROOT),
        capture_output=True,
    )
    return result.stdout.decode().strip()
```

**Where to call**: Before any batch write (compile job, bulk distill, auto-link). NOT on individual captures (too frequent).

**Effort**: ~15 minutes. Non-negotiable prerequisite for everything else.

### 2.2 Provenance Tracking

**Risk**: After 6 months, vault mixes human-written, Telegram-captured, LLM-generated, and conversation-extracted content. Cannot audit, filter, or bulk-revert.

**Implementation**: Every file or section created by automated processes includes provenance metadata.

Frontmatter:
```yaml
---
type: concept
source: distiller          # human | telegram | distiller | compile
source_session: abc123     # Claude session ID, if applicable
generated_at: 2026-04-03
confidence: 0.85           # extraction confidence
---
```

Inline sections (for content appended to existing files):
```markdown
<!-- auto:distiller session=abc123 date=2026-04-03 -->
## Auto-generated Summary
...
<!-- /auto:distiller -->
```

**Rules**:
- `source: human` — user wrote it directly in Obsidian
- `source: telegram` — captured via Telegram bot
- `source: distiller` — extracted from Claude conversation
- `source: compile` — generated by compile job (future)
- Every source tag includes a timestamp and confidence score
- The `source` field gets indexed in `vault_nodes` (single column, not 7)

**Effort**: ~20 minutes (frontmatter template + vault_ops write functions).

### 2.3 Thread Pool Saturation Guard

**Risk**: `_on_vault_write()` spawns 7 background tasks per file. Batch operations (20 files = 140 tasks) saturate the `ThreadPoolExecutor` and block concurrent captures.

**Implementation**:
```python
# In vault_ops.py
_BATCH_MODE = False
_BATCH_QUEUE: list[Path] = []

def enter_batch_mode():
    """Suppress per-file post-write hooks. Call process_batch() when done."""
    global _BATCH_MODE
    _BATCH_MODE = True
    _BATCH_QUEUE.clear()

def exit_batch_mode():
    """Run post-write hooks once for all accumulated files."""
    global _BATCH_MODE
    _BATCH_MODE = False
    if _BATCH_QUEUE:
        # Single reindex pass instead of 7*N individual hook calls
        vault_indexer.index_multiple_files(_BATCH_QUEUE)
        _BATCH_QUEUE.clear()

def _on_vault_write(file_path: Path):
    if _BATCH_MODE:
        _BATCH_QUEUE.append(file_path)
        return
    # ... existing 7-hook chain
```

**Where to call**: Wrap any batch operation (compile, distill, bulk-import) in `enter_batch_mode()` / `exit_batch_mode()`.

**Effort**: ~30 minutes. Prevents the executor from choking on batch writes.

### 2.4 Quality Gate for LLM-Generated Content

**Risk**: LLM hallucinations preserved as facts. Bad summaries, wrong dimension links, hallucinated wikilinks to nonexistent pages.

**Implementation**:
```python
# In a new core/quality_gate.py
def validate_vault_write(content: str, file_path: Path) -> list[str]:
    """Check LLM-generated content before writing to vault."""
    issues = []
    # Check wikilinks point to real files
    for link in re.findall(r'\[\[([^\]]+)\]\]', content):
        target = config.VAULT_PATH / f"{link}.md"
        if not target.exists():
            issues.append(f"Broken wikilink: [[{link}]]")
    # Check frontmatter is valid YAML
    if content.startswith("---"):
        try:
            yaml_block = content.split("---")[1]
            yaml.safe_load(yaml_block)
        except:
            issues.append("Invalid YAML frontmatter")
    # Check for suspiciously long content (hallucination signal)
    word_count = len(content.split())
    if word_count > 2000:
        issues.append(f"Unusually long ({word_count} words) — review before writing")
    return issues
```

**Rules**: Any automated vault write runs through `validate_vault_write()`. If issues found, write to a staging area (`vault/Staging/`) instead of the target location. User reviews via `/review-staging` command (future).

**Effort**: ~30 minutes.

---

## Part 3: The 90-Minute Foundation (Ship Now)

These are the changes both grills endorsed. They persist what the system already computes but throws away.

### 3.1 Persist ExtractionResult to captures_log

The intent extractor already runs on every actionable capture. It extracts intent, title, people, project, due_date, priority. Then the confirmation UI shows it. Then it's discarded (stored in `_pending_extractions` dict with 15-minute TTL).

**Schema change** (migration step 28):
```sql
ALTER TABLE captures_log ADD COLUMN intent TEXT;
ALTER TABLE captures_log ADD COLUMN extracted_title TEXT;
ALTER TABLE captures_log ADD COLUMN extracted_project TEXT;
ALTER TABLE captures_log ADD COLUMN extracted_due_date TEXT;
ALTER TABLE captures_log ADD COLUMN extracted_people TEXT;  -- JSON array
ALTER TABLE captures_log ADD COLUMN extraction_confidence REAL;
CREATE INDEX idx_captures_intent ON captures_log(intent);
CREATE INDEX idx_captures_due ON captures_log(extracted_due_date);
```

**Code change** (capture.py, ~10 lines):
After extraction succeeds and before showing confirmation UI, persist to captures_log:
```python
if extraction and extraction.confidence > 0.3:
    await execute(
        "UPDATE captures_log SET intent=?, extracted_title=?, "
        "extracted_project=?, extracted_due_date=?, extracted_people=?, "
        "extraction_confidence=? WHERE id=?",
        (extraction.intent, extraction.title, extraction.project,
         extraction.due_date, json.dumps(extraction.people),
         extraction.confidence, capture_id),
    )
```

**Effort**: ~15 minutes.

### 3.2 Allow Unlinked Captures

When extraction succeeds but dimension confidence is low, skip the dimension bouncer. Save capture with `dimensions_json = '[]'` and show the extraction result instead.

**Code change** (capture.py, `_handle_low_confidence`, ~15 lines):
```python
# If intent extraction provided a confident result, skip dimension picker
if extraction and extraction.confidence > 0.3:
    # Save as unlinked — dimension TBD
    # User sees: "Task noted: Call Sarah / Due: Friday / No dimension yet"
    # Triage happens in /today
    return
# Else: existing dimension picker flow
```

**Effort**: ~20 minutes.

### 3.3 Intent-Aware Context Loading for /today

Add unlinked captures and intent-grouped summaries to the morning briefing context.

**Code change** (context_loader.py, `_COMMAND_QUERIES["today"]`, ~5 lines):
```sql
-- Add to today's queries:
SELECT intent, extracted_title, extracted_project, extracted_due_date
FROM captures_log
WHERE intent IS NOT NULL
  AND (dimensions_json = '[]' OR dimensions_json IS NULL)
  AND created_at > datetime('now', '-7 days')
ORDER BY created_at DESC
LIMIT 20;
```

The LLM in `/today` will naturally surface these: "You have 3 unlinked captures: a task about calling Sarah (due Friday), a question about investment portfolios, and an idea about voice-controlled Obsidian."

**Effort**: ~10 minutes.

### 3.4 Classifier Feedback Loop

When the user confirms an extraction, feed the confirmed intent back into the keyword tier. Currently, `keyword_feedback` only stores dimension corrections. Extend it to store intent corrections too.

**Code change** (capture.py confirm handler + classifier.py, ~15 lines):
```python
# On confirm, if extraction had a project match:
if extraction.project:
    # Strengthen project keyword association
    await execute(
        "INSERT INTO keyword_feedback (keyword, dimension, weight, source) "
        "VALUES (?, ?, 1.0, 'extraction_confirm')",
        (extraction.project.lower(), matched_dimension),
    )
```

**Effort**: ~15 minutes.

**Total 90-minute foundation: ~75 minutes actual.**

---

## Part 4: Conversation Distiller (Build After Foundation)

This is the winning path from both grills. Not bulk import. Not a compile layer. A distiller that extracts atomic knowledge from Claude sessions and routes through the existing capture pipeline.

### 4.1 What Gets Extracted

From each Claude session, extract 3-5 atomic notes in these categories:

| Category | Example | Vault Target |
|---|---|---|
| **Decision** | "Chose event-driven over batch compile because system is already hook-based" | `vault/Concepts/` or `vault/Inbox/` |
| **Lesson** | "Module-level mock pollution: use setdefault, not direct assignment" | `tasks/lessons.md` + `vault/Inbox/` |
| **Architecture** | "5-tier classification: noise -> keyword -> zero-shot -> embedding -> LLM" | `vault/Concepts/` |
| **Insight** | "The richest knowledge source is Claude conversations, not Telegram" | `vault/Inbox/` |
| **TODO** | "Add provenance tracking to all automated vault writes" | `action_items` via capture pipeline |

### 4.2 How It Works

**Trigger**: End of each Claude Code session (hook or manual `/distill` command).

**Pipeline**:
```
Session JSONL
  --> Extract assistant text blocks (skip tool calls, system messages)
  --> Chunk into conversation turns
  --> LLM pass: "Extract 3-5 atomic knowledge notes from this session"
  --> Each note gets:
      - title (imperative for decisions/TODOs, noun phrase for concepts)
      - category (decision/lesson/architecture/insight/todo)
      - confidence (0-1)
      - source_session: session ID
      - related_files: files touched in this session
  --> Route through capture pipeline:
      - Intent extraction (already built)
      - Dimension classification (already built)  
      - Vault write (already built)
      - Graph integration (already built)
  --> Provenance: source=distiller, source_session=ID
```

**Key design choices**:
- **Extract atomic notes, not summaries**. A 10-line concept note is worth more than a 4000-word transcript.
- **Route through existing pipeline**. No new architecture. The capture handler, intent extractor, classifier, and vault writer all already work. The distiller is just a new input source.
- **Human review gate**. Distilled notes go to `vault/Inbox/` with `status: unprocessed`. The user reviews in Obsidian or via `/review-inbox` (future command). Nothing auto-publishes to `vault/Concepts/` without explicit confirmation.
- **Cost cap**. Each distill pass processes ~2000 words of conversation (the "interesting" parts after filtering tool calls). At ~$0.003 per pass, cost is negligible.

### 4.3 Session Filtering

Not all 50 sessions deserve distillation. Filter by:

```python
def should_distill(session_path: Path) -> bool:
    """Only distill sessions with substantial assistant output."""
    size = session_path.stat().st_size
    if size < 10_000:  # < 10KB = trivial session
        return False
    if size > 20_000_000:  # > 20MB = likely automated/bulk
        return False
    # Check for actual assistant text (not just tool calls)
    assistant_chars = count_assistant_text(session_path)
    return assistant_chars > 2000  # At least ~400 words of substance
```

### 4.4 Effort Estimate

| Component | Effort | Dependencies |
|---|---|---|
| JSONL parser (extract assistant text) | 30 min | None |
| Distill prompt + LLM call | 30 min | ai_client.py |
| Route results through capture pipeline | 20 min | 90-min foundation |
| Provenance tagging | 10 min | Section 2.2 |
| `/distill` command handler | 20 min | None |
| Tests | 45 min | All above |
| Total | ~2.5 hours | |

---

## Part 5: The Compile Layer (Future, Gated)

The compile layer is NOT premature forever. It's premature now, at 129 files and 0 concepts. Here are the conditions that trigger building it:

### Activation Gates

| Gate | Threshold | Rationale |
|---|---|---|
| Vault file count | > 500 | Below this, manual + /graduate handles it |
| Concept notes | > 20 | Need a concept corpus before auto-maintaining it |
| Unlinked captures backlog | > 50 | Below this, /today triage handles it |
| Distiller running for | > 30 days | Need conversation-derived knowledge accumulating |
| User requests it | — | The user knows their pain better than any metric |

### What It Would Do (When Activated)

Karpathy's pattern, calibrated for this system:

1. **Orphan detection**: Find vault files with 0 incoming edges. Suggest connections.
2. **Concept graduation**: Auto-detect themes appearing 3+ times across daily notes. Propose concept stubs. (This is `/graduate` on a schedule.)
3. **Summary refresh**: For concept notes older than 30 days with new linked captures, regenerate the summary section.
4. **Dimension auto-link**: For unlinked captures older than 7 days, auto-assign dimension using full vault context (not just capture text).
5. **Stale action cleanup**: Flag action items older than 14 days with no status change.

All compile outputs go through the quality gate (Section 2.4) and provenance tracking (Section 2.2). All writes use batch mode (Section 2.3).

### What It Would NOT Do

- Auto-create files in `vault/Concepts/` without human review (staging area first)
- Modify human-written content (only append auto-sections within `<!-- auto: -->` markers)
- Run more than once per week (cost and risk containment)
- Process more than 50 files per run (executor saturation guard)

---

## Part 6: Build Order

### Phase 0: Safety Infrastructure (prerequisite, ~1.5 hours)
- [ ] 2.1 Vault backup helper (15 min)
- [ ] 2.2 Provenance frontmatter convention (20 min)
- [ ] 2.3 Batch mode for vault writes (30 min)
- [ ] 2.4 Quality gate for LLM content (30 min)

### Phase 1: 90-Minute Foundation (~75 min)
- [ ] 3.1 Persist ExtractionResult to captures_log (15 min)
- [ ] 3.2 Allow unlinked captures (20 min)
- [ ] 3.3 Intent-aware /today context (10 min)
- [ ] 3.4 Classifier feedback loop (15 min)
- [ ] Tests for Phase 1 (30 min)

**Validation gate**: Use the bot for 14 days. Measure:
- How many captures have intent persisted?
- How many are unlinked vs. classified?
- Does /today surface unlinked captures usefully?
- Does the classifier improve from feedback?

### Phase 2: Conversation Distiller (~2.5 hours)
- [ ] 4.1-4.4 Build distiller (2.5 hours)
- [ ] Backfill: distill 10 highest-value past sessions as pilot
- [ ] Tests (45 min)

**Validation gate**: Run distiller on 10 sessions. Review output quality:
- Are the 3-5 notes per session actually useful?
- Do they integrate cleanly with the vault graph?
- Does search quality improve or degrade?

### Phase 3: Compile Layer (future, gated)
- [ ] Only after activation gates are met (Section 5)
- [ ] Estimate: 4-6 hours including tests
- [ ] Requires Phase 0 safety infrastructure

---

## Part 7: Success Metrics

### 30-Day Targets (After Phase 1)

| Metric | Current | Target | How to Measure |
|---|---|---|---|
| Captures with intent | 0 | 80%+ | `SELECT COUNT(*) FROM captures_log WHERE intent IS NOT NULL` |
| Unlinked captures triaged within 24h | N/A | 90%+ | `SELECT COUNT(*) WHERE dimensions_json != '[]' AND ...` |
| Classifier accuracy (user corrections) | Unknown | < 2 corrections/week | `SELECT COUNT(*) FROM keyword_feedback WHERE ...` |
| /today includes capture context | No | Yes | Manual check |
| User captures per day | 0.9 | 2+ | Organic growth from reduced friction |

### 60-Day Targets (After Phase 2)

| Metric | Target | How to Measure |
|---|---|---|
| Distilled notes per session | 3-5 | Count inbox items with source=distiller |
| Vault concept notes | 10+ | File count in vault/Concepts/ |
| Graph connectivity | +50% edges | `SELECT COUNT(*) FROM vault_edges` |
| Search relevance (subjective) | "Finds what I need" | User feedback |

### Activation Metrics (Phase 3 Gate)

| Metric | Threshold |
|---|---|
| Vault files | > 500 |
| Concept notes | > 20 |
| Unlinked backlog | > 50 |
| Distiller age | > 30 days |

---

## Appendix: References

- **Karpathy's self-improving wiki**: raw --> LLM compile --> indexed .md wiki --> Q&A --> outputs filed back. The feedback loop is the key, not the compile step.
- **Omar's research curation**: Collect raw (highlights, tweets, papers) --> consolidate (weekly synthesis with linking) --> distill (original insight). Maps to Capture --> Compile --> Query but emphasizes human synthesis at the distill step.
- **Grill Report 2026-04-02** (conversation import): REJECTED bulk import. Winner: post-session distiller.
- **Grill Report 2026-04-03** (3-layer pipeline): APPROVE WITH REVISIONS. Winner: 90-minute path + kill compile job.
- **Intelligence Vision 2026-04-01**: Defines 7 dimensions of intelligence. The pipeline serves dimensions 1 (Understand), 2 (Connect), and 3 (Anticipate).
- **FEA Architecture** (from MEMORY.md): Fixed Entity Architecture. ICOR hierarchy = Layer 1 (Fixed Ontology), Vault files = Layer 2 (Documents), NLP entities = Layer 3. New content connects instantly via cosine similarity.

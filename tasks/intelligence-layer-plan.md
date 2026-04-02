# Intelligence Layer Implementation Plan

## Phase 0: Documentation Discovery (COMPLETE)

### Allowed APIs (verified from codebase):

**Capture Pipeline (`handlers/capture.py`):**
- Main handler: `async def handle_capture(update: Update, context: ContextTypes.DEFAULT_TYPE)`
- `is_actionable` used at line 234 to gate `insert_action_item()`
- Insertion point for extraction: line 233 (after vault writes, before action item creation)
- Confirmation buttons pattern: `InlineKeyboardButton` with `callback_data=_cb({"a": "fb_ok", "m": msg_id})`

**Classifier (`core/classifier.py`):**
- `ClassificationResult` dataclass: `matches`, `is_noise`, `is_actionable`, `execution_time_ms`
- `_ACTION_PATTERNS` regex at line 71: `r"(?i)\b(need to|should|todo|must|have to|going to|reminder|deadline|action|follow.?up|schedule)\b"`
- `DimensionScore` dataclass: `dimension`, `confidence`, `method`

**AI Client (`core/ai_client.py`):**
- `get_ai_client()` returns unified client (Gemini or Anthropic based on AI_PROVIDER)
- `get_ai_model()` returns model string
- Gemini backend via `_GeminiMessages.create()` translates Anthropic-style calls
- Call pattern: `client.messages.create(model=model, max_tokens=N, system=[...], messages=[...])`

**DB Operations (`core/db_ops.py`):**
- `insert_action_item(description, source, icor_element=None, icor_project=None, db_path=None) -> int`
- `get_pending_actions(db_path=None) -> list[dict]` — queries `status='pending'`
- `update_action_status(action_id, new_status, db_path=None)`
- `execute(sql, params=(), db_path=None)` — raw SQL execution

**Scheduled Jobs (`handlers/scheduled.py`):**
- `job_morning_briefing` calls `_call_claude("today")` and sends raw AI text to `brain-daily` topic
- `_send_to_topic(bot, topic_name, text, keyboard=None)` — sends to forum topic
- `_record_job_run(job_name)` — tracks in `scheduler_state` table
- Registration: `job_queue.run_daily(func, time=time(H, M, tzinfo=CST), name="name")`
- Weekly: `job_queue.run_daily(func, time=..., days=(DAY_NUM,), name="name")`

**Notion Sync:**
- `action_to_notion_task(action_dict, registry_data) -> dict` — builds Notion properties
- Property builders: `build_title_property`, `build_date_property`, `build_relation_property`, `build_status_property`
- Missing from current mapper: `Due` (date), `People` (relation), `Priority` (select vs status)
- Immediate push: instantiate `NotionClientWrapper`, call `create_page(parent={"data_source_id": TASKS_COLLECTION_ID}, properties=props)`
- Tasks collection: `231fda46-1a19-8125-95f4-000ba3e22ea6`

**Migration (`scripts/migrate-db.py`):**
- Steps use pattern: `if current_step < N:` with SQL execution
- Current highest step: 25 (search_filters indexes)
- New tables: `CREATE TABLE IF NOT EXISTS`, add indexes
- Alter existing: `ALTER TABLE action_items ADD COLUMN due_date TEXT`

**Notion Registry (`data/notion-registry.json`):**
- Top keys: `dimensions`, `key_elements`, `goals`, `projects`, `dashboard_page_id`
- Projects: `{"project_name": {"notion_id": "uuid", "status": "Doing", ...}}`
- People: via `RegistryManager.set_person()` but key may not exist yet

### Anti-Patterns to Avoid:
- Do NOT call LLM on every capture — gate on `is_actionable`
- Do NOT auto-create Notion tasks — use confirmation flow first
- Do NOT add new dependencies (no GLiNER, no spaCy, no FlashRank)
- Do NOT modify the existing 5-tier classifier — add extraction AFTER it
- Do NOT wait for 10pm sync — create Notion tasks immediately on confirm

---

## Phase 1: Morning Briefing Reminders (Step 1)

### Tasks:
1. Add migration step 26: `ALTER TABLE action_items ADD COLUMN due_date TEXT`
2. Add migration step 26 also: `CREATE TABLE reminders (id INTEGER PRIMARY KEY, action_item_id INTEGER, remind_at TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')))`
3. Add migration step 26 also: `CREATE TABLE extraction_feedback (id INTEGER PRIMARY KEY, capture_id INTEGER, field_name TEXT, proposed_value TEXT, confirmed_value TEXT, was_correct INTEGER, created_at TEXT DEFAULT (datetime('now')))`
4. Update `db_ops.py`: add `get_due_actions(db_path=None)` function: `SELECT * FROM action_items WHERE due_date <= date('now') AND status = 'pending'`
5. Update `handlers/scheduled.py` `job_morning_briefing`: query due actions and include in the briefing context passed to `_call_claude("today")`
6. Update `core/formatter.py`: add `format_due_actions(actions) -> str` for HTML formatting

### Verification:
- `python scripts/migrate-db.py` succeeds
- `sqlite3 data/brain.db ".schema action_items"` shows `due_date` column
- `sqlite3 data/brain.db "SELECT * FROM reminders"` works
- Existing 991 tests still pass

---

## Phase 2: Intent Extraction (Step 2)

### Tasks:
1. Create `core/intent_extractor.py` (~100 lines):
   - `async def extract_intent(text: str, registry_data: dict) -> ExtractionResult`
   - `ExtractionResult` dataclass: `intent` (task/idea/reflection/update/link/question), `title` (str), `people` (list[str]), `project` (str|None), `due_date` (str|None), `priority` (str|None), `confidence` (float)
   - Uses `get_ai_client()` / `get_ai_model()` with a structured JSON prompt
   - Prompt includes active project names from `registry_data["projects"]` for matching
   - Fuzzy-match `project` against registry keys using `difflib.get_close_matches()`
2. Wire into `handlers/capture.py` at line 233:
   - If `result.is_actionable`: call `extract_intent(text, registry_data)`
   - Pass `extraction` result to the confirmation flow (Phase 3)
3. Load registry data in capture handler (use `RegistryManager` or read from file)

### Verification:
- Unit test: mock AI client, verify ExtractionResult parsed correctly
- Unit test: fuzzy matching against sample project names
- Integration test: send "Need to call Sarah about pitch deck by Friday" → verify extraction returns correct fields

---

## Phase 3: Confirmation Flow (Step 3)

### Tasks:
1. Add `format_extraction_confirmation(extraction: ExtractionResult) -> FormatResult` to `core/formatter.py`:
   - HTML format: "✅ **Task:** {title}\n📅 **Due:** {due_date}\n👤 **Person:** {people}\n📁 **Project:** {project}"
   - Returns formatted text
2. Add confirmation inline keyboard in `handlers/capture.py`:
   - After extraction, reply with formatted extraction + Confirm/Edit buttons
   - `callback_data=_cb({"a": "ext_ok", "eid": extraction_id})` for Confirm
   - `callback_data=_cb({"a": "ext_edit", "eid": extraction_id})` for Edit
3. Store pending extractions in `extraction_feedback` table (or in-memory dict with TTL)
4. Add callback handler `handle_extraction_confirm` in `handlers/capture.py` or new `handlers/extraction.py`:
   - On Confirm: create Notion task immediately with structured fields
   - Call `action_to_notion_task()` but with enriched action dict (due_date, project relation, people relation)
   - Use `NotionClientWrapper` to push immediately
   - Log confirmation to `extraction_feedback` table
5. Add callback handler `handle_extraction_edit`:
   - Show inline keyboard with field-specific edit options
   - Allow correcting title, due_date, project, person individually

### Verification:
- Send a capture → receive confirmation message with correct fields
- Tap Confirm → Notion task appears with due_date, person, project
- Tap Edit → can modify fields
- `extraction_feedback` table has a row

---

## Phase 4: Reminders (Step 4)

### Tasks:
1. On extraction confirm: if `due_date` is today or tomorrow, schedule `run_once()`:
   - `context.job_queue.run_once(send_reminder, when=reminder_time, data={"action_id": id, "title": title})`
2. Persist reminder to `reminders` table
3. On bot startup (`app.py`): reload pending reminders from SQLite and re-register with JobQueue
4. `send_reminder` callback: send message to `brain-actions` topic with the task details

### Verification:
- Create a task due tomorrow → reminder appears in brain-actions at 7am
- Restart bot → reminder still fires
- Complete a task → reminder is cancelled

---

## Phase 5: Autopilot Jobs (Week 2 - Step 5)

### Tasks:
1. Add `job_weekly_connections` to `handlers/scheduled.py`:
   - `job_queue.run_daily(job_weekly_connections, time=time(14, 0, tzinfo=CST), days=(2,), name="weekly_connections")`
   - Calls `_call_claude("connect")` with auto-generated topic pairs from recent captures
   - Sends result to `brain-insights` topic
2. Add `job_weekly_contradiction_scan`:
   - Runs Sunday 5pm
   - Queries recent captures and journal entries
   - Uses LLM to find contradictions
   - Sends findings to `brain-insights`
3. Note: `emerge_biweekly` already exists — just verify it's working

### Verification:
- After registration, `job_queue.jobs()` shows new jobs
- Manual trigger produces output in brain-insights topic

---

## Phase 6: Enhanced Morning Briefing (Week 2 - Step 6)

### Tasks:
1. Update the `today` command prompt (`.claude/commands/brain/today.md`) to include:
   - "Tasks due today" section from `get_due_actions()`
   - "Overdue tasks" section
   - "Upcoming deadlines (next 3 days)" section
2. Update `core/context_loader.py` `gather_command_context("today")`:
   - Add query for due/overdue actions
   - Add query for People with overdue check-ins

### Verification:
- Morning briefing at 7am includes due tasks section
- Overdue tasks are highlighted

---

## Final Phase: Verification

1. Run full test suite: `cd scripts/brain-bot && python -m pytest tests/ -x`
2. Run bot manually: `python scripts/brain-bot/app.py`
3. Send test captures via Telegram and verify the full loop:
   - "Need to call Sarah about the pitch deck by Friday" → extraction → confirm → Notion task
   - "Just thinking about life today" → no extraction (not actionable) → normal classification
4. Verify morning briefing includes due tasks
5. Verify reminder fires for due-today tasks

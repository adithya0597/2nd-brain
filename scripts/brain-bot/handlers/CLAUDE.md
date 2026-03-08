# scripts/brain-bot/handlers/ — Telegram Command & Message Handlers

## Purpose

All Telegram-facing handler logic: message capture/routing, slash commands, interactive button actions (CallbackQuery), classification feedback, scheduled automations (JobQueue), and the dashboard command.

## Module Summary

| Module | Description |
|---|---|
| `__init__.py` | `register_all(application)` — imports and registers handler modules in order: capture, commands, actions, feedback, dashboard |
| `capture.py` | Listens for text messages (in inbox topic if configured), classifies via 4-tier pipeline, routes to vault + SQLite, replies with confirmation + feedback buttons |
| `commands.py` | 19 command handlers mapped via `CommandHandler`. Edit-in-place progress pattern: sends "Processing..." then edits with result |
| `actions.py` | CallbackQuery handlers: Complete/Snooze/Delegate action items, Save-to-Vault for reports, Dismiss messages. Delegate uses `ConversationHandler` for multi-step flow |
| `feedback.py` | Classification correction flow: Correct (increments keyword success), Wrong (shows dimension picker via inline keyboard), Select Dimension (updates `classifications` + `keyword_feedback` tables) |
| `scheduled.py` | 10 scheduled jobs registered via PTB's `JobQueue`. Includes AI-powered (morning briefing, drift, emerge, projects, resources) and non-AI (dashboard, evening prompt, vault reindex, keyword expansion, Notion sync) |
| `dashboard.py` | `/dashboard` command handler + pinned message updater. Sends full 8-section ICOR dashboard with quick-action buttons |
| `app_home.py` | Settings/info views accessible via the bot |

## Capture Pipeline (`capture.py`)

1. Text message arrives → `MessageHandler` with owner filter
2. If inbox topic configured: only processes messages in that topic
3. Classifies via `MessageClassifier.classify()` (4-tier pipeline)
4. If noise: replies with guidance, stops
5. Vault writes: appends to daily note (`## Log` section), creates inbox entry file
6. If actionable: inserts into `action_items` table
7. Logs classification to `classifications` table
8. Saves to `captures_log` table with dimension metadata
9. Replies with confirmation + Correct/Wrong feedback buttons (inline keyboard)

## Command Pipeline (`commands.py`)

1. `/command` arrives → `CommandHandler` with owner filter (via `_owner_check()`)
2. Sends initial "Processing..." message (edit-in-place progress)
3. Gathers context via `gather_command_context()` (SQL + vault + graph + Notion)
4. Loads system context (CLAUDE.md) + command prompt (`.claude/commands/brain/{cmd}.md`)
5. Calls Anthropic API with assembled messages (async via `AsyncAnthropic`)
6. Writes result back to vault via `_write_command_output_to_vault()`
7. Edits the "Processing..." message with the final result (or sends to designated topic)
8. Splits long messages via `send_long_message()` if they exceed 4096 chars

Available commands: `today`, `close`, `drift`, `emerge`, `ideas`, `schedule`, `ghost`, `status`, `sync`, `projects`, `resources`, `trace`, `connect`, `challenge`, `graduate`, `context`, `find`, `help`, `engage`, `dashboard`

Special commands:
- `/status` — SQLite-only, no AI call
- `/sync` — Python-native Notion sync, no AI call
- `/help` — Static command listing
- `/find` — Hybrid search (FTS5 + vector + graph)
- `/dashboard` — Delegated to `dashboard.py`

## Background Processing Pattern

PTB v21 is async-native. No manual threading needed:
```python
async def _handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Processing...")  # Immediate feedback
    result = await _run_ai_command(command_name, user_input)  # Async work
    await msg.edit_text(result, parse_mode=ParseMode.HTML)    # Edit in place
```
CPU-bound work (embeddings, indexing) offloaded via `core.async_utils.run_in_executor()`.
`concurrent_updates(8)` in `ApplicationBuilder` allows up to 8 handlers to process simultaneously.

## Scheduled Jobs (`scheduled.py`)

Jobs registered via PTB's `JobQueue` in `register_jobs(job_queue)`:

| Job Function | Schedule | AI? | Output Topic |
|---|---|---|---|
| `job_morning_briefing` | Daily 7am CST | Yes | `brain-daily` |
| `job_evening_prompt` | Daily 9pm CST | No (template) | `brain-daily` |
| `job_dashboard_refresh` | Daily 6am, 6pm CST | No (SQLite) | `brain-dashboard` |
| `job_notion_sync` | Daily 10pm CST | Optional | Silent (errors to `brain-daily`) |
| `job_drift_report` | Sunday 6pm CST | Yes | `brain-drift` |
| `job_emerge_biweekly` | Wed 2pm CST (bi-weekly) | Yes | `brain-insights` |
| `job_weekly_project_summary` | Monday 9am CST | Yes | `brain-projects` |
| `job_monthly_resource_digest` | 1st 10am CST | Yes | `brain-resources` |
| `job_vault_reindex` | Daily 5am CST | No | Silent |
| `job_keyword_expansion` | Sunday 2am CST | Yes | Silent |

Jobs use `job_queue.run_daily(callback, time=time(..., tzinfo=CST))`. Bi-weekly and monthly jobs use date guards inside the callback.

## Dashboard (`dashboard.py`)

- `/dashboard` command sends a full 8-section dashboard with inline keyboard buttons
- Quick-action buttons trigger corresponding commands (Today, Ideas, Drift, etc.)
- Pinned message in `brain-dashboard` topic updated on schedule with compact summary
- Uses `core.dashboard_builder` for HTML generation and `core.formatter._cb()` for callback data

## Gotchas

- **No ack() needed**: Unlike Slack, Telegram has no 3-second timeout. Commands can take as long as needed. The edit-in-place pattern provides user feedback instead.
- **Owner filter**: Each handler checks `OWNER_TELEGRAM_ID` individually via helper functions. The global `OwnerFilter` in `app.py` only covers the catch-all handler.
- **Forum topic routing**: Messages are sent to specific topics via `message_thread_id` parameter. If a topic ID is not configured in `config.TOPICS`, messages fall back to the group's general thread.
- **Feedback uses CallbackQuery**: Correct/Wrong buttons are `InlineKeyboardButton` with JSON-encoded callback data. Dimension picker is also inline keyboard (not a modal like Slack).
- **ConversationHandler for delegate**: The delegate flow uses PTB's `ConversationHandler` with states `DELEGATE_NAME` and `DELEGATE_NOTES` for multi-step input collection.
- **Bi-weekly emerge**: Uses a date-based guard (checks if ISO week number is even) instead of a counter. Survives bot restarts correctly.
- **Job run tracking**: `_record_job_run()` logs each successful job execution to the `scheduled_runs` table for debugging and audit.
- **`_AUTO_VAULT_WRITE_COMMANDS`**: Commands in this set auto-save to `vault/Reports/`. Commands `today` and `close` append to the daily note instead. Commands `projects` and `resources` offer a "Save to Vault" button (manual).
- **HTML parse mode**: All formatted messages use `parse_mode=ParseMode.HTML`. Special characters in user input must be escaped via `html.escape()` before embedding in formatted output.

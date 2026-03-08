# scripts/slack-bot/handlers/ — Slack Event & Command Handlers

## Purpose

All Slack-facing handler logic: message capture/routing, slash commands, interactive button actions, classification feedback, and scheduled automations.

## Module Summary

| Module | Description |
|---|---|
| `__init__.py` | `register_all(app)` — imports and registers all four handler modules in order |
| `capture.py` | Listens for messages in `#brain-inbox`, classifies via 4-tier pipeline, routes to ICOR dimension channels, cross-posts to `#brain-projects` / `#brain-resources`, writes to vault + SQLite |
| `commands.py` | 14 slash commands mapped via `_COMMAND_MAP`. Each `ack()`s immediately, then spawns a background thread to gather context + call Claude + post results |
| `actions.py` | Interactive button handlers: Complete/Snooze/Delegate action items, Save-to-Vault for reports, Dismiss messages. Delegate opens a Slack modal. |
| `feedback.py` | Classification correction flow: Correct (increments keyword success), Wrong (shows dimension picker), Select Dimension (updates `classifications` + `keyword_feedback` tables) |
| `scheduled.py` | 10 scheduled jobs registered via `schedule` library. Includes AI-powered (morning briefing, drift, emerge, projects, resources) and non-AI (dashboard, evening prompt, vault reindex, keyword expansion, Notion sync) |

## Capture Pipeline (`capture.py`)

1. Message arrives in `#brain-inbox` → `handle_message` event listener
2. Filters: ignore bot messages, `message_changed`, non-owner users
3. Spawns background thread → `_process_capture()`
4. Classifies via `MessageClassifier.classify()` (4-tier pipeline)
5. If noise: replies with guidance, stops
6. Vault writes: appends to daily note (`## Log` section), creates inbox entry file
7. If actionable: inserts into `action_items` table
8. Logs classification to `classifications` table
9. Routes to ICOR dimension channel(s) with confidence/method metadata
10. Cross-posts to `#brain-projects` or `#brain-resources` if keyword thresholds met
11. Replies in thread with confirmation + Correct/Wrong feedback buttons

## Command Pipeline (`commands.py`)

1. Slash command arrives → `ack()` immediately with "Processing..."
2. Spawns background thread → `_run_ai_command()`
3. Gathers context via `gather_command_context()` (SQL + vault + graph + Notion)
4. Loads system context (CLAUDE.md) + command prompt (`.claude/commands/brain/{cmd}.md`)
5. Calls Anthropic API with assembled messages
6. Writes result back to vault via `_write_command_output_to_vault()`
7. Posts result to designated output channel (or DM)
8. Splits text into 3000-char Slack blocks if needed

Special commands:
- `/brain-status` — SQLite-only, no AI call
- `/brain-sync` — Python-native Notion sync, no AI call

## Background Processing Pattern

All handlers follow the same pattern to avoid Slack's 3-second ack timeout:
```
def handler(ack, command, client):
    ack("Processing...")              # Respond immediately
    thread = threading.Thread(        # Background work
        target=_do_work,
        args=(client, ...),
        daemon=True,
    )
    thread.start()
```
Each background thread creates its own `asyncio.new_event_loop()` for async DB/API calls.

## Scheduled Jobs (`scheduled.py`)

| Job Function | Schedule | AI? | Output Channel |
|---|---|---|---|
| `job_morning_briefing` | Daily 7am | Yes | `#brain-daily` |
| `job_evening_prompt` | Daily 9pm | No (template) | `#brain-daily` |
| `job_dashboard_refresh` | Daily 6am, 6pm | No (SQLite) | `#brain-dashboard` |
| `job_notion_sync` | Daily 10pm | Optional | Silent (errors to `#brain-daily`) |
| `job_drift_report` | Sunday 6pm | Yes | `#brain-drift` |
| `job_emerge_biweekly` | Wed 2pm (bi-weekly) | Yes | `#brain-insights` |
| `job_weekly_project_summary` | Monday 9am | Yes | `#brain-projects` |
| `job_monthly_resource_digest` | 1st 10am | Yes | `#brain-resources` |
| `job_vault_reindex` | Daily 5am | No | Silent |
| `job_keyword_expansion` | Sunday 2am | Yes | Silent |

## Gotchas

- **Concurrent file write race**: Each inbox message spawns a daemon thread. Two captures arriving simultaneously can race on `append_to_daily_note()` (read-modify-write without lock). **Audit: add `threading.Lock` or write queue to serialize vault writes.**
- **No progress feedback**: After ack, there is no typing indicator or placeholder. AI commands take 20-60s. Results post to a different channel with no "result ready" notification to the user. **Audit: add `chat_postEphemeral` after command completes.**
- **Feedback doesn't re-route**: "Wrong" → dimension picker → updates DB and edits message, but never re-posts the capture to the correct dimension channel. **Audit: add cross-post after correction.**
- **Feedback success_count bug**: `handle_correct` WHERE clause requires `success_count + fail_count > 0`, so the first confirmation for any keyword is silently dropped.
- **Bi-weekly emerge**: Uses a global `_emerge_counter` — counts every Wednesday, only runs on even counts. **Counter resets on bot restart, permanently shifting the schedule.** Audit: persist last-run timestamps in SQLite.
- **Channel ID caching**: Both `capture.py` and `commands.py` lazily resolve channel IDs on the hot path. First message triggers up to 30 Slack API calls (probe + delete per channel). **Audit: pre-resolve at startup in app.py.**
- **Monthly resource digest**: Registered as a daily job with a `today.day != 1` guard. This means it runs the check daily but only fires on the 1st.
- **Feedback learning loop**: Correct/Wrong buttons update `keyword_feedback` table. The `job_keyword_expansion` scheduled job uses Claude to suggest new keywords from corrections, then hot-reloads them into the classifier.
- **`_AUTO_VAULT_WRITE_COMMANDS`**: Commands in this set auto-save to `vault/Reports/`. Commands `today` and `close-day` append to the daily note instead. Commands `projects` and `resources` offer a "Save to Vault" button (manual).
- **Delegate modal**: Uses `views.open` with `private_metadata` to pass action ID and channel info through the modal submission flow.
- **5x `_run_async` duplication**: The `asyncio.new_event_loop()` pattern is copy-pasted across capture.py, commands.py, actions.py, feedback.py, scheduled.py. **Audit: centralize into `core/async_utils.py`.**

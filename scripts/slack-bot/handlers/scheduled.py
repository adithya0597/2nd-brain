"""Scheduled automations for the Second Brain Slack bot.

Uses the `schedule` library for cron-like job definitions.
Jobs are registered at startup and run in the background via app.py.
"""
import json
import logging
import sqlite3
from datetime import datetime, timedelta

import anthropic
import schedule
from slack_sdk import WebClient

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DB_PATH,
    DIMENSION_KEYWORDS,
    NOTION_COLLECTIONS,
    NOTION_REGISTRY_PATH,
    NOTION_TOKEN,
    VAULT_PATH,
    load_dynamic_keywords,
)
from core.async_utils import run_async
from core.context_loader import (
    build_claude_messages,
    gather_command_context,
    load_command_prompt,
    load_system_context,
)
from core.db_ops import (
    execute,
    get_attention_scores,
    get_neglected_elements,
    get_pending_actions,
    get_recent_journal,
    query,
)
from core.formatter import (
    format_dashboard,
    format_error,
    format_sync_report,
)
from core.notion_client import NotionClientWrapper
from core.notion_sync import NotionSync

logger = logging.getLogger(__name__)


def _record_job_run(job_name: str):
    """Record that a scheduled job ran successfully."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT OR REPLACE INTO scheduler_state (job_name, last_run_at, updated_at) "
            "VALUES (?, datetime('now'), datetime('now'))",
            (job_name,),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.warning("Failed to record job run: %s", job_name)


def _should_run_biweekly(job_name: str) -> bool:
    """Check if a bi-weekly job should run (2 weeks since last run)."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.execute(
            "SELECT last_run_at FROM scheduler_state WHERE job_name = ?",
            (job_name,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row or not row[0]:
            return True
        last_run = datetime.fromisoformat(row[0])
        return datetime.now() - last_run >= timedelta(days=13)
    except Exception:
        return True


def _resolve_channel_ids(client: WebClient) -> dict[str, str]:
    """Get channel name -> ID mapping."""
    mapping = {}
    try:
        result = client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in result.get("channels", []):
            mapping[ch["name"]] = ch["id"]
    except Exception:
        logger.exception("Failed to resolve channel IDs for scheduler")
    return mapping


def _call_claude(brain_command: str, user_input: str = "") -> str:
    """Gather context, call Claude, return text response."""
    context = run_async(gather_command_context(brain_command))
    system_ctx = load_system_context()
    prompt = load_command_prompt(brain_command)
    messages = build_claude_messages(brain_command, user_input, context)

    ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = ai_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=f"{system_ctx}\n\n---\n\n{prompt}",
        messages=messages,
    )
    return response.content[0].text


def _post_text(client: WebClient, channel_id: str, text: str, header: str = None):
    """Post text to a channel, splitting if needed."""
    blocks = []
    if header:
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header, "emoji": True},
            }
        )

    # Split long text into 3000-char sections
    chunks = [text[i : i + 3000] for i in range(0, len(text), 3000)]
    for chunk in chunks:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Auto-generated | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                }
            ],
        }
    )

    client.chat_postMessage(
        channel=channel_id,
        text=header or "Scheduled update",
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Job Functions
# ---------------------------------------------------------------------------


def job_morning_briefing(client: WebClient, channel_ids: dict):
    """Daily 7am: Full AI-powered morning briefing."""
    try:
        logger.info("Running morning briefing job")
        result = _call_claude("today")
        ch = channel_ids.get("brain-daily")
        if ch:
            _post_text(client, ch, result, header="Morning Briefing")
        _record_job_run("morning_briefing")
    except Exception:
        logger.exception("Morning briefing job failed")


def job_evening_prompt(client: WebClient, channel_ids: dict):
    """Daily 9pm: Structured evening review prompt (template, no full AI)."""
    try:
        logger.info("Running evening prompt job")
        pending = run_async(get_pending_actions())
        recent = run_async(get_recent_journal(days=1))

        journal_status = "Yes" if recent else "Not yet"
        pending_count = len(pending)

        text = (
            f"*Evening Review Time*\n\n"
            f"*Journal today:* {journal_status}\n"
            f"*Pending actions:* {pending_count}\n\n"
            f"*Reflection prompts:*\n"
            f"1. What went well today?\n"
            f"2. What challenged you?\n"
            f"3. What will you carry forward to tomorrow?\n"
            f"4. Any new ideas or insights?\n\n"
            f"_Run `/brain-close` when you're ready for the full evening review._"
        )

        ch = channel_ids.get("brain-daily")
        if ch:
            _post_text(client, ch, text, header="Evening Review")
        _record_job_run("evening_prompt")
    except Exception:
        logger.exception("Evening prompt job failed")


def job_dashboard_refresh(client: WebClient, channel_ids: dict):
    """Twice daily: SQLite dashboard refresh."""
    try:
        logger.info("Running dashboard refresh job")
        pending = run_async(get_pending_actions())
        attention = run_async(get_attention_scores())
        neglected = run_async(get_neglected_elements())

        # Build ICOR data grouped by dimension
        icor_data: dict[str, list] = {}
        for score in attention:
            dim = score.get("dimension", "Unknown")
            if dim not in icor_data:
                icor_data[dim] = []
            icor_data[dim].append(score)

        blocks = format_dashboard(icor_data, [], pending)

        # Add neglected elements
        if neglected:
            neglected_text = "\n".join(
                f"- *{n['name']}* ({n.get('dimension', 'N/A')}) - "
                f"{int(n.get('days_since', 0))} days silent"
                for n in neglected[:5]
            )
            blocks.insert(
                -1,
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Neglected Elements:*\n{neglected_text}",
                    },
                },
            )

        ch = channel_ids.get("brain-dashboard")
        if ch:
            client.chat_postMessage(
                channel=ch,
                text="Dashboard Refresh",
                blocks=blocks,
            )
        _record_job_run("dashboard_refresh")
    except Exception:
        logger.exception("Dashboard refresh job failed")


def job_notion_sync(client: WebClient, channel_ids: dict):
    """Daily 10pm: Python-native Notion sync (post summary on error)."""
    if not NOTION_TOKEN:
        logger.warning("NOTION_TOKEN not set — skipping Notion sync")
        return
    try:
        logger.info("Running Notion sync job (Python-native)")

        async def _do_sync():
            notion = NotionClientWrapper(token=NOTION_TOKEN)
            try:
                syncer = NotionSync(
                    client=notion,
                    registry_path=NOTION_REGISTRY_PATH,
                    db_path=DB_PATH,
                    vault_path=VAULT_PATH,
                    collection_ids=NOTION_COLLECTIONS,
                    ai_client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None,
                    ai_model=ANTHROPIC_MODEL,
                )
                return await syncer.run_full_sync()
            finally:
                await notion.close()

        result = run_async(_do_sync())
        logger.info("Notion sync completed: %s", result.summary())

        # Post summary if there were errors
        if result.errors:
            ch = channel_ids.get("brain-daily")
            if ch:
                blocks = format_sync_report(result)
                client.chat_postMessage(
                    channel=ch,
                    text="Notion sync completed with errors",
                    blocks=blocks,
                )
        _record_job_run("notion_sync")
    except Exception:
        logger.exception("Notion sync job failed")
        ch = channel_ids.get("brain-daily")
        if ch:
            blocks = format_error("Scheduled Notion sync failed. Check bot logs.")
            client.chat_postMessage(
                channel=ch,
                text="Notion sync error",
                blocks=blocks,
            )


def job_drift_report(client: WebClient, channel_ids: dict):
    """Weekly Sunday 6pm: Drift analysis."""
    try:
        logger.info("Running weekly drift report job")
        result = _call_claude("drift")
        ch = channel_ids.get("brain-drift")
        if ch:
            _post_text(client, ch, result, header="Weekly Drift Report")
        _record_job_run("drift_report")
    except Exception:
        logger.exception("Drift report job failed")


def job_emerge_biweekly(client: WebClient, channel_ids: dict):
    """Bi-weekly Wednesday 2pm: Pattern synthesis."""
    if not _should_run_biweekly("emerge_biweekly"):
        logger.info("Skipping emerge job (less than 2 weeks since last run)")
        return

    try:
        logger.info("Running bi-weekly emerge job")
        result = _call_claude("emerge")
        ch = channel_ids.get("brain-insights")
        if ch:
            _post_text(client, ch, result, header="Pattern Synthesis Report")
        _record_job_run("emerge_biweekly")
    except Exception:
        logger.exception("Emerge job failed")


def job_weekly_project_summary(client: WebClient, channel_ids: dict):
    """Weekly Monday 9am: AI-powered project summary."""
    try:
        logger.info("Running weekly project summary job")
        result = _call_claude("projects")
        ch = channel_ids.get("brain-projects")
        if ch:
            _post_text(client, ch, result, header="Weekly Project Summary")
        _record_job_run("weekly_project_summary")
    except Exception:
        logger.exception("Weekly project summary job failed")


def job_monthly_resource_digest(client: WebClient, channel_ids: dict):
    """Monthly 1st at 10am: AI-powered resource digest."""
    today = datetime.now()
    if today.day != 1:
        return  # Only run on the 1st of the month
    try:
        logger.info("Running monthly resource digest job")
        result = _call_claude("resources")
        ch = channel_ids.get("brain-resources")
        if ch:
            _post_text(client, ch, result, header="Monthly Resource Digest")
        _record_job_run("monthly_resource_digest")
    except Exception:
        logger.exception("Monthly resource digest job failed")


def job_vault_reindex(client: WebClient, channel_ids: dict):
    """Daily 5am: Re-index vault files and journal entries."""
    try:
        from core.vault_indexer import run_full_index as index_vault
        from core.journal_indexer import run_full_index as index_journal
        vault_count = index_vault()
        journal_count = index_journal()
        logger.info("Vault reindex: %d files, %d journal entries", vault_count, journal_count)
        # Populate FTS5 index after vault reindex
        try:
            from core.fts_index import populate_fts
            fts_count = populate_fts(db_path=str(DB_PATH), vault_path=str(VAULT_PATH))
            logger.info("FTS5 index populated: %d files", fts_count)
        except Exception as e:
            logger.warning("FTS5 population failed: %s", e)
        _record_job_run("vault_reindex")
    except Exception:
        logger.exception("Vault reindex job failed")


def job_keyword_expansion(client: WebClient, channel_ids: dict):
    """Weekly Sunday 2am: Expand keywords from recent corrections using Claude."""
    if not ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping keyword expansion")
        return

    try:
        logger.info("Running weekly keyword expansion job")

        # Get recent corrections
        corrections = run_async(query(
            "SELECT message_text, primary_dimension, user_correction "
            "FROM classifications "
            "WHERE user_correction IS NOT NULL "
            "AND corrected_at >= datetime('now', '-7 days') "
            "ORDER BY corrected_at DESC LIMIT 50",
        ))

        if not corrections:
            logger.info("No recent corrections — skipping keyword expansion")
            return

        # Format corrections for Claude
        correction_text = "\n".join(
            f"- \"{c['message_text'][:100]}\" was classified as {c['primary_dimension'] or 'none'}, "
            f"corrected to {c['user_correction']}"
            for c in corrections
        )

        current_keywords = json.dumps(
            {d: kws[:10] for d, kws in DIMENSION_KEYWORDS.items()},
            indent=2,
        )

        ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = ai_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": (
                    "Based on these recent misclassifications and corrections, suggest new keywords "
                    "for each life dimension. Return ONLY a JSON object mapping dimension names to "
                    "arrays of new keyword strings. Each keyword should be lowercase.\n\n"
                    f"Current keywords (sample):\n{current_keywords}\n\n"
                    f"Recent corrections:\n{correction_text}\n\n"
                    "Suggest 3-8 new keywords per dimension that would have caught these "
                    "misclassifications. Only suggest keywords that are clearly associated "
                    "with one dimension. Reply with ONLY the JSON object."
                ),
            }],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        suggestions = json.loads(raw)

        # Insert suggestions into keyword_feedback
        inserted = 0
        for dim, keywords in suggestions.items():
            # Validate dimension name
            matched_dim = None
            for known_dim in DIMENSION_KEYWORDS:
                if known_dim.lower() == dim.lower() or known_dim == dim:
                    matched_dim = known_dim
                    break
            if not matched_dim:
                continue

            for kw in keywords:
                if not isinstance(kw, str) or len(kw) < 2:
                    continue
                try:
                    run_async(query(
                        "INSERT OR IGNORE INTO keyword_feedback (dimension, keyword, source, success_count) "
                        "VALUES (?, ?, 'llm_suggested', 1)",
                        (matched_dim, kw.lower()),
                    ))
                    inserted += 1
                except Exception:
                    pass

        logger.info("Keyword expansion: %d suggestions from %d corrections", inserted, len(corrections))
        _record_job_run("keyword_expansion")

        # Reload dynamic keywords into the classifier
        try:
            from handlers.capture import get_classifier
            new_keywords = load_dynamic_keywords()
            get_classifier().update_keywords(new_keywords)
            logger.info("Classifier keywords hot-reloaded")
        except Exception:
            logger.warning("Could not hot-reload classifier keywords")

    except Exception:
        logger.exception("Keyword expansion job failed")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def job_weekly_review(client: WebClient, channel_ids: dict):
    """Weekly Sunday 7pm: GTD weekly review."""
    try:
        logger.info("Running weekly review job")
        result = _call_claude("weekly-review")
        ch = channel_ids.get("brain-daily")
        if ch:
            _post_text(client, ch, result, header="Weekly Review")
        _record_job_run("weekly_review")
    except Exception:
        logger.exception("Weekly review job failed")


def job_resolve_pending_captures(client: WebClient, channel_ids: dict):
    """Every 5 min: auto-file pending captures that timed out."""
    try:
        from config import BOUNCER_TIMEOUT_MINUTES

        rows = run_async(query(
            "SELECT id, message_text, message_ts, primary_dimension, channel_id, "
            "bouncer_dm_ts, bouncer_dm_channel "
            "FROM pending_captures WHERE status = 'pending' "
            "AND created_at < datetime('now', ?)",
            (f"-{BOUNCER_TIMEOUT_MINUTES} minutes",),
        ))

        if not rows:
            return

        logger.info("Auto-filing %d timed-out pending captures", len(rows))
        for row in rows:
            try:
                run_async(execute(
                    "UPDATE pending_captures SET status = 'timeout', "
                    "user_selection = primary_dimension, resolved_at = datetime('now') "
                    "WHERE id = ?",
                    (row["id"],),
                ))

                # Route via normal path
                from handlers.capture import _process_bouncer_resolution

                _process_bouncer_resolution(
                    client, row["message_text"], row["message_ts"],
                    row["primary_dimension"] or "Systems & Environment",
                    row["channel_id"],
                )

                # Update DM
                if row.get("bouncer_dm_ts") and row.get("bouncer_dm_channel"):
                    try:
                        client.chat_update(
                            channel=row["bouncer_dm_channel"],
                            ts=row["bouncer_dm_ts"],
                            blocks=[{
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f":clock1: *Auto-filed to {row['primary_dimension']}* (no response)",
                                },
                            }],
                            text="Auto-filed",
                        )
                    except Exception:
                        pass
            except Exception:
                logger.exception("Failed to resolve pending capture id=%d", row["id"])
    except Exception:
        logger.exception("Error in job_resolve_pending_captures")


def _run_job(job_func, client, channel_ids):
    """Wrapper to catch exceptions in scheduled jobs."""
    try:
        job_func(client, channel_ids)
    except Exception:
        logger.exception("Scheduled job %s failed", job_func.__name__)


def register_schedules(app):
    """Configure all scheduled jobs. Called from app.py at startup."""
    client = app.client
    channel_ids = _resolve_channel_ids(client)

    if not channel_ids:
        logger.warning("No channels resolved -- scheduled jobs may fail to post")

    # Daily 7am: Morning briefing
    schedule.every().day.at("07:00").do(_run_job, job_morning_briefing, client, channel_ids)

    # Daily 9pm: Evening review prompt
    schedule.every().day.at("21:00").do(_run_job, job_evening_prompt, client, channel_ids)

    # Daily 6am, 6pm: Dashboard refresh
    schedule.every().day.at("06:00").do(_run_job, job_dashboard_refresh, client, channel_ids)
    schedule.every().day.at("18:00").do(_run_job, job_dashboard_refresh, client, channel_ids)

    # Daily 10pm: Notion sync (silent)
    schedule.every().day.at("22:00").do(_run_job, job_notion_sync, client, channel_ids)

    # Weekly Sunday 6pm: Drift report
    schedule.every().sunday.at("18:00").do(_run_job, job_drift_report, client, channel_ids)

    # Bi-weekly Wednesday 2pm: Pattern synthesis (counter-based)
    schedule.every().wednesday.at("14:00").do(_run_job, job_emerge_biweekly, client, channel_ids)

    # Weekly Monday 9am: Project summary
    schedule.every().monday.at("09:00").do(_run_job, job_weekly_project_summary, client, channel_ids)

    # Monthly 1st at 10am: Resource digest (daily check with day-of-month guard)
    schedule.every().day.at("10:00").do(_run_job, job_monthly_resource_digest, client, channel_ids)

    # Weekly Sunday 7pm: GTD weekly review
    schedule.every().sunday.at("19:00").do(_run_job, job_weekly_review, client, channel_ids)

    # Weekly Sunday 2am: Keyword expansion from corrections
    schedule.every().sunday.at("02:00").do(_run_job, job_keyword_expansion, client, channel_ids)

    # Daily 5am: Vault + journal re-index
    schedule.every().day.at("05:00").do(_run_job, job_vault_reindex, client, channel_ids)

    # Every 5 min: Resolve timed-out pending captures
    schedule.every(5).minutes.do(_run_job, job_resolve_pending_captures, client, channel_ids)

    logger.info(
        "Registered %d scheduled jobs, channel_ids resolved: %d",
        len(schedule.get_jobs()),
        len(channel_ids),
    )

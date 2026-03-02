"""Scheduled automations for the Second Brain Slack bot.

Uses the `schedule` library for cron-like job definitions.
Jobs are registered at startup and run in the background via app.py.
"""
import asyncio
import json
import logging
from datetime import datetime

import anthropic
import schedule
from slack_sdk import WebClient

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DB_PATH,
    NOTION_COLLECTIONS,
    NOTION_REGISTRY_PATH,
    NOTION_TOKEN,
    VAULT_PATH,
)
from core.context_loader import (
    build_claude_messages,
    gather_command_context,
    load_command_prompt,
    load_system_context,
)
from core.db_ops import (
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

# Counter for bi-weekly emerge job
_emerge_counter = 0


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


def _run_async(coro):
    """Run an async coroutine from sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _call_claude(brain_command: str, user_input: str = "") -> str:
    """Gather context, call Claude, return text response."""
    context = _run_async(gather_command_context(brain_command))
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
    except Exception:
        logger.exception("Morning briefing job failed")


def job_evening_prompt(client: WebClient, channel_ids: dict):
    """Daily 9pm: Structured evening review prompt (template, no full AI)."""
    try:
        logger.info("Running evening prompt job")
        pending = _run_async(get_pending_actions())
        recent = _run_async(get_recent_journal(days=1))

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
    except Exception:
        logger.exception("Evening prompt job failed")


def job_dashboard_refresh(client: WebClient, channel_ids: dict):
    """Twice daily: SQLite dashboard refresh."""
    try:
        logger.info("Running dashboard refresh job")
        pending = _run_async(get_pending_actions())
        attention = _run_async(get_attention_scores())
        neglected = _run_async(get_neglected_elements())

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

        result = _run_async(_do_sync())
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
    except Exception:
        logger.exception("Drift report job failed")


def job_emerge_biweekly(client: WebClient, channel_ids: dict):
    """Bi-weekly Wednesday 2pm: Pattern synthesis."""
    global _emerge_counter
    _emerge_counter += 1
    if _emerge_counter % 2 != 0:
        logger.info("Skipping emerge job (odd week)")
        return

    try:
        logger.info("Running bi-weekly emerge job")
        result = _call_claude("emerge")
        ch = channel_ids.get("brain-insights")
        if ch:
            _post_text(client, ch, result, header="Pattern Synthesis Report")
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
    except Exception:
        logger.exception("Monthly resource digest job failed")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


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

    logger.info(
        "Registered %d scheduled jobs, channel_ids resolved: %d",
        len(schedule.get_jobs()),
        len(channel_ids),
    )

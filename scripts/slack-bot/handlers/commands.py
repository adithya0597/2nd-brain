"""Slash command handlers for Second Brain bot.

Each command acks immediately, processes in background, and posts to the
designated output channel.
"""
import json
import logging
from datetime import datetime

import anthropic
from slack_bolt import App

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DB_PATH,
    NOTION_COLLECTIONS,
    NOTION_REGISTRY_PATH,
    NOTION_TOKEN,
    VAULT_PATH,
)
from core.async_utils import executor, run_async
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
    format_help,
    format_sync_report,
)
from core.notion_client import NotionClientWrapper
from core.notion_sync import NotionSync
from core.vault_ops import (
    append_to_daily_note,
    create_concept_file,
    create_report_file,
    create_weekly_plan,
    ensure_daily_note,
)

logger = logging.getLogger(__name__)

# Commands that auto-save reports to vault
_AUTO_VAULT_WRITE_COMMANDS = {
    "drift", "emerge", "ideas", "ghost", "challenge",
    "trace", "connect",
}


def _write_command_output_to_vault(brain_command: str, result_text: str, user_input: str):
    """Write AI command output back to the vault.

    This is the core "close the loop" function — ensures command outputs
    don't just go to Slack but also enrich the vault.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        if brain_command == "close-day":
            # Append summary to daily note + index journal entry
            ensure_daily_note(today)
            append_to_daily_note(
                today,
                f"\n## Evening Review\n\n{result_text[:3000]}",
            )
            # Re-index the updated daily note
            try:
                from core.journal_indexer import run_full_index
                run_full_index()
            except Exception:
                logger.debug("Journal re-index skipped")

        elif brain_command == "today":
            # Create/update daily note with the morning plan
            ensure_daily_note(today)
            append_to_daily_note(
                today,
                f"\n## Morning Plan\n\n{result_text[:3000]}",
            )

        elif brain_command == "schedule":
            # Save as weekly plan file
            create_weekly_plan(result_text, date=today)

        elif brain_command in _AUTO_VAULT_WRITE_COMMANDS:
            # Auto-save report-style commands
            create_report_file(brain_command, result_text)

        elif brain_command == "graduate":
            # Save the full report AND create individual concept stubs
            create_report_file("graduate", result_text)

    except Exception:
        logger.exception("Error writing %s output to vault", brain_command)

# Command -> (brain_command, output_channel)
# output_channel=None means DM the user
_COMMAND_MAP = {
    "/brain-today": ("today", "brain-daily"),
    "/brain-close": ("close-day", "brain-daily"),
    "/brain-drift": ("drift", "brain-drift"),
    "/brain-emerge": ("emerge", "brain-insights"),
    "/brain-ideas": ("ideas", "brain-ideas"),
    "/brain-schedule": ("schedule", "brain-daily"),
    "/brain-ghost": ("ghost", "brain-insights"),
    "/brain-projects": ("projects", "brain-projects"),
    "/brain-resources": ("resources", "brain-resources"),
    "/brain-context": ("context-load", None),
    "/brain-trace": ("trace", "brain-insights"),
    "/brain-connect": ("connect", "brain-insights"),
    "/brain-challenge": ("challenge", "brain-insights"),
    "/brain-graduate": ("graduate", "brain-insights"),
    "/brain-find": ("find", None),
    "/brain-review": ("weekly-review", "brain-daily"),
}

# Channel name -> resolved ID cache (populated by app.py at startup)
_channel_ids: dict[str, str] = {}


def set_channel_ids(ids: dict[str, str]):
    """Set channel ID cache (called from app.py at startup)."""
    _channel_ids.update(ids)


def _run_ai_command(client, user_id, brain_command, output_channel, user_input):
    """Background worker: gather context, call Claude, post result."""
    try:
        context = run_async(gather_command_context(brain_command, user_input=user_input))

        system_ctx = load_system_context()
        prompt = load_command_prompt(brain_command)
        messages = build_claude_messages(brain_command, user_input, context)

        ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = ai_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_ctx,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=messages,
        )

        result_text = response.content[0].text

        try:
            from core.token_logger import log_token_usage
            log_token_usage(response, caller=f"command_{brain_command}", model=ANTHROPIC_MODEL)
        except Exception:
            pass

        # Write output back to vault (close the loop)
        _write_command_output_to_vault(brain_command, result_text, user_input)

        # Post to output channel or DM
        if output_channel and output_channel in _channel_ids:
            channel_id = _channel_ids[output_channel]
        else:
            # DM the user
            dm = client.conversations_open(users=[user_id])
            channel_id = dm["channel"]["id"]

        # Slack has a 3000 char limit per section block; split if needed
        if len(result_text) <= 3000:
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": result_text},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"/{brain_command} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        }
                    ],
                },
            ]
        else:
            # Split into chunks
            chunks = [result_text[i : i + 3000] for i in range(0, len(result_text), 3000)]
            blocks = []
            for chunk in chunks:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": chunk},
                    }
                )
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"/{brain_command} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        }
                    ],
                },
            )

        # Add save-to-vault button for reports (if not already auto-saved)
        if brain_command in ("projects", "resources"):
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Save to Vault"},
                            "action_id": "save_to_vault",
                            "value": json.dumps(
                                {
                                    "command": brain_command,
                                    "content": result_text[:2900],
                                }
                            ),
                        }
                    ],
                }
            )

        client.chat_postMessage(
            channel=channel_id,
            text=f"Results for /{brain_command}",
            blocks=blocks,
        )

        # Notify user that results are ready
        if output_channel and output_channel in _channel_ids:
            try:
                client.chat_postEphemeral(
                    channel=_channel_ids[output_channel],
                    user=user_id,
                    text=f"Your /{brain_command} results are ready in #{output_channel}",
                )
            except Exception:
                logger.debug("Could not send result notification")

    except Exception:
        logger.exception("Error running AI command: %s", brain_command)
        try:
            dm = client.conversations_open(users=[user_id])
            blocks = format_error(f"Failed to execute /{brain_command}. Check bot logs.")
            client.chat_postMessage(
                channel=dm["channel"]["id"],
                text=f"Error running /{brain_command}",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to send error DM")


def _run_sync_command(client, user_id, user_input):
    """Background worker: run Python-native Notion sync."""
    try:
        if not NOTION_TOKEN:
            dm = client.conversations_open(users=[user_id])
            blocks = format_error("NOTION_TOKEN not configured. Set it in .env to enable Notion sync.")
            client.chat_postMessage(channel=dm["channel"]["id"], text="Notion sync error", blocks=blocks)
            return

        async def _do_sync():
            notion = NotionClientWrapper(token=NOTION_TOKEN)
            try:
                # Determine if selective sync was requested
                entity_types = [t.strip() for t in user_input.split(",") if t.strip()] if user_input else []

                syncer = NotionSync(
                    client=notion,
                    registry_path=NOTION_REGISTRY_PATH,
                    db_path=DB_PATH,
                    vault_path=VAULT_PATH,
                    collection_ids=NOTION_COLLECTIONS,
                    ai_client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None,
                    ai_model=ANTHROPIC_MODEL,
                )

                if entity_types:
                    return await syncer.run_selective_sync(entity_types)
                return await syncer.run_full_sync()
            finally:
                await notion.close()

        result = run_async(_do_sync())

        # Post sync report as DM
        dm = client.conversations_open(users=[user_id])
        blocks = format_sync_report(result)
        client.chat_postMessage(
            channel=dm["channel"]["id"],
            text="Notion Sync Report",
            blocks=blocks,
        )

    except Exception:
        logger.exception("Error running sync command")
        try:
            dm = client.conversations_open(users=[user_id])
            blocks = format_error("Notion sync failed. Check bot logs.")
            client.chat_postMessage(channel=dm["channel"]["id"], text="Sync error", blocks=blocks)
        except Exception:
            logger.exception("Failed to send sync error DM")


def _run_status_command(client, user_id):
    """Quick SQLite-only status dashboard (no AI call)."""
    try:
        pending = run_async(get_pending_actions())
        neglected = run_async(get_neglected_elements())
        attention = run_async(get_attention_scores())
        recent = run_async(get_recent_journal(days=1))

        journal_today = "Yes" if recent else "No"

        # Build ICOR data for dashboard formatter
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

        # Add quick stats
        blocks.insert(
            1,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Quick Stats:*\n"
                        f"- Pending actions: {len(pending)}\n"
                        f"- Journaled today: {journal_today}\n"
                        f"- Neglected elements: {len(neglected)}"
                    ),
                },
            },
        )

        dashboard_id = _channel_ids.get("brain-dashboard")
        if dashboard_id:
            client.chat_postMessage(
                channel=dashboard_id,
                text="Brain Status Dashboard",
                blocks=blocks,
            )
        else:
            dm = client.conversations_open(users=[user_id])
            client.chat_postMessage(
                channel=dm["channel"]["id"],
                text="Brain Status Dashboard",
                blocks=blocks,
            )

    except Exception:
        logger.exception("Error running status command")


def register(app: App):
    """Register all slash command handlers."""

    # AI-powered commands
    for slack_cmd, (brain_cmd, output_ch) in _COMMAND_MAP.items():

        def _make_handler(brain_command, output_channel):
            def handler(ack, command, client):
                ack(f"Processing /{brain_command}...")
                user_id = command.get("user_id", "")
                user_input = command.get("text", "")
                executor.submit(_run_ai_command, client, user_id, brain_command, output_channel, user_input)

            return handler

        app.command(slack_cmd)(_make_handler(brain_cmd, output_ch))

    # Quick status command (no AI)
    @app.command("/brain-status")
    def handle_status(ack, command, client):
        ack("Fetching status...")
        user_id = command.get("user_id", "")
        executor.submit(_run_status_command, client, user_id)

    # Notion sync command (Python-native, no AI)
    @app.command("/brain-sync")
    def handle_sync(ack, command, client):
        ack("Running Notion sync...")
        user_id = command.get("user_id", "")
        user_input = command.get("text", "")
        executor.submit(_run_sync_command, client, user_id, user_input)

    # Help command (no AI, ephemeral response)
    @app.command("/brain-help")
    def handle_help(ack, command, client):
        ack()
        try:
            blocks = format_help()
            client.chat_postEphemeral(
                channel=command.get("channel_id", ""),
                user=command.get("user_id", ""),
                text="Second Brain Commands",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to send help message")

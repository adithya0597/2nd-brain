"""Slash command handlers for Second Brain bot.

Each command acks immediately, processes in background, and posts to the
designated output channel.
"""
import asyncio
import json
import logging
import threading
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

# Command -> (brain_command, output_channel)
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
}

# Channel name -> resolved ID cache
_channel_ids: dict[str, str] = {}


def _ensure_channel_ids(client):
    """Lazily resolve channel name -> ID mapping."""
    if _channel_ids:
        return
    try:
        result = client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in result.get("channels", []):
            _channel_ids[ch["name"]] = ch["id"]
    except Exception:
        logger.exception("Failed to resolve channel IDs")


def _run_ai_command(client, user_id, brain_command, output_channel, user_input):
    """Background worker: gather context, call Claude, post result."""
    try:
        loop = asyncio.new_event_loop()
        context = loop.run_until_complete(gather_command_context(brain_command))
        loop.close()

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

        result_text = response.content[0].text

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

        # Add save-to-vault button for reports
        if brain_command in ("drift", "emerge", "ideas", "ghost", "projects", "resources"):
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

        loop = asyncio.new_event_loop()

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

        result = loop.run_until_complete(_do_sync())
        loop.close()

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
        loop = asyncio.new_event_loop()
        pending = loop.run_until_complete(get_pending_actions())
        neglected = loop.run_until_complete(get_neglected_elements())
        attention = loop.run_until_complete(get_attention_scores())
        recent = loop.run_until_complete(get_recent_journal(days=1))
        loop.close()

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
                _ensure_channel_ids(client)
                user_id = command.get("user_id", "")
                user_input = command.get("text", "")
                thread = threading.Thread(
                    target=_run_ai_command,
                    args=(client, user_id, brain_command, output_channel, user_input),
                    daemon=True,
                )
                thread.start()

            return handler

        app.command(slack_cmd)(_make_handler(brain_cmd, output_ch))

    # Quick status command (no AI)
    @app.command("/brain-status")
    def handle_status(ack, command, client):
        ack("Fetching status...")
        _ensure_channel_ids(client)
        user_id = command.get("user_id", "")
        thread = threading.Thread(
            target=_run_status_command,
            args=(client, user_id),
            daemon=True,
        )
        thread.start()

    # Notion sync command (Python-native, no AI)
    @app.command("/brain-sync")
    def handle_sync(ack, command, client):
        ack("Running Notion sync...")
        _ensure_channel_ids(client)
        user_id = command.get("user_id", "")
        user_input = command.get("text", "")
        thread = threading.Thread(
            target=_run_sync_command,
            args=(client, user_id, user_input),
            daemon=True,
        )
        thread.start()

"""Inbox message routing handler.

Listens for messages in #brain-inbox, classifies the ICOR dimension,
routes to the appropriate channel, and saves to daily note + vault inbox.
"""
import asyncio
import logging
import re
import threading
from datetime import datetime

import anthropic
from slack_bolt import App

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DIMENSION_CHANNELS,
    DIMENSION_KEYWORDS,
    OWNER_SLACK_ID,
    PROJECT_KEYWORDS,
    RESOURCE_KEYWORDS,
)
from core.db_ops import insert_action_item
from core.formatter import format_capture_confirmation, format_error
from core.vault_ops import append_to_daily_note, create_inbox_entry

logger = logging.getLogger(__name__)

# Patterns that suggest an actionable item
_ACTION_PATTERNS = re.compile(
    r"\b(need to|should|must|todo|action|reminder|deadline|follow.up|schedule|book|call|email|buy|pay|submit|send)\b",
    re.IGNORECASE,
)


def _classify_dimension_keywords(text: str) -> str | None:
    """Fast keyword-based dimension classification. Returns dimension name or None."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for dimension, keywords in DIMENSION_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            scores[dimension] = count

    if not scores:
        return None

    best = max(scores, key=scores.get)
    # Only return if there's a clear winner (or only one match)
    if len(scores) == 1 or scores[best] >= 2:
        return best
    # Ambiguous -- fall through to AI classification
    return None


def _classify_dimension_ai(text: str) -> str:
    """Use Claude to classify text into an ICOR dimension."""
    dimensions = ", ".join(DIMENSION_CHANNELS.keys())
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=50,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Classify this text into exactly one of these life dimensions: {dimensions}\n\n"
                    f"Text: {text}\n\n"
                    "Reply with ONLY the dimension name, nothing else."
                ),
            }
        ],
    )
    result = response.content[0].text.strip()
    # Validate the response is a known dimension
    for dim in DIMENSION_CHANNELS:
        if dim.lower() in result.lower():
            return dim
    # Default fallback
    return "Systems & Environment"


def _is_actionable(text: str) -> bool:
    """Heuristic check for whether text looks like an action item."""
    return bool(_ACTION_PATTERNS.search(text))


def _detect_project_mention(text: str) -> bool:
    """Check if text mentions project-related keywords."""
    text_lower = text.lower()
    return sum(1 for kw in PROJECT_KEYWORDS if kw in text_lower) >= 2


def _detect_resource_mention(text: str) -> bool:
    """Check if text mentions resource-related keywords."""
    text_lower = text.lower()
    return sum(1 for kw in RESOURCE_KEYWORDS if kw in text_lower) >= 2


def _process_capture(client, event, channel_ids: dict):
    """Background processing for a captured message."""
    text = event.get("text", "")
    user = event.get("user", "")
    channel = event.get("channel", "")
    ts = event.get("ts", "")

    if not text:
        return

    # Owner check
    if OWNER_SLACK_ID and user != OWNER_SLACK_ID:
        return

    try:
        # 1. Classify dimension
        dimension = _classify_dimension_keywords(text)
        if dimension is None:
            if ANTHROPIC_API_KEY:
                dimension = _classify_dimension_ai(text)
            else:
                dimension = "Systems & Environment"

        target_channel_name = DIMENSION_CHANNELS.get(dimension, "brain-systems")
        target_channel_id = channel_ids.get(target_channel_name)

        # 2. Save to vault: daily note + inbox entry
        today = datetime.now().strftime("%Y-%m-%d")
        append_to_daily_note(
            today,
            f"- **[Slack Capture]** {text} _(routed to {dimension})_",
            section="## Log",
        )
        create_inbox_entry(text, source="slack")

        # 3. Insert action item if it looks actionable
        if _is_actionable(text):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    insert_action_item(
                        description=text,
                        source="slack-inbox",
                        icor_element=dimension,
                    )
                )
            finally:
                loop.close()

        # 4. Post to dimension channel
        if target_channel_id:
            client.chat_postMessage(
                channel=target_channel_id,
                text=f"*New capture from inbox:*\n> {text}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*New capture from inbox:*\n> {text}",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Routed from #brain-inbox | {today}",
                            }
                        ],
                    },
                ],
            )

        # 4b. Cross-post to PARA channels if keywords match
        if _detect_project_mention(text):
            projects_ch = channel_ids.get("brain-projects")
            if projects_ch:
                client.chat_postMessage(
                    channel=projects_ch,
                    text=f"Project-related capture from inbox",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":file_folder: *Project-related capture:*\n> {text}",
                            },
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Cross-posted from #brain-inbox → #{target_channel_name} | {today}",
                                }
                            ],
                        },
                    ],
                )

        if _detect_resource_mention(text):
            resources_ch = channel_ids.get("brain-resources")
            if resources_ch:
                client.chat_postMessage(
                    channel=resources_ch,
                    text=f"Resource-related capture from inbox",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":books: *Resource-related capture:*\n> {text}",
                            },
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Cross-posted from #brain-inbox → #{target_channel_name} | {today}",
                                }
                            ],
                        },
                    ],
                )

        # 5. Reply in thread in #brain-inbox
        blocks = format_capture_confirmation(text, dimension, target_channel_name)
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"Captured and routed to #{target_channel_name}",
            blocks=blocks,
        )

    except Exception:
        logger.exception("Error processing capture")
        try:
            blocks = format_error("Failed to process capture. Check bot logs.")
            client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text="Error processing capture",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to send error message")


def register(app: App):
    """Register the inbox capture handler."""

    # Resolve channel IDs at registration time
    _channel_ids: dict[str, str] = {}

    def _ensure_channel_ids():
        if _channel_ids:
            return
        try:
            result = app.client.conversations_list(types="public_channel,private_channel", limit=200)
            for ch in result.get("channels", []):
                _channel_ids[ch["name"]] = ch["id"]
        except Exception:
            logger.exception("Failed to resolve channel IDs")

    @app.event("message")
    def handle_message(event, client, say):
        """Handle messages -- route brain-inbox captures in background."""
        _ensure_channel_ids()

        channel = event.get("channel", "")
        inbox_id = _channel_ids.get("brain-inbox")

        # Only process messages in #brain-inbox
        if not inbox_id or channel != inbox_id:
            return

        # Ignore bot messages and message_changed events
        if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            return

        # Process in background thread to avoid 3-second timeout
        thread = threading.Thread(
            target=_process_capture,
            args=(client, event, _channel_ids),
            daemon=True,
        )
        thread.start()

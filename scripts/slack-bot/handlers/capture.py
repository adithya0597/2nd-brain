"""Inbox message routing handler.

Listens for messages in #brain-inbox, classifies the ICOR dimension,
routes to the appropriate channel, and saves to daily note + vault inbox.
"""
import json
import logging
from datetime import datetime

from slack_bolt import App

from config import (
    CHANNELS,
    DIMENSION_CHANNELS,
    OWNER_SLACK_ID,
    PROJECT_KEYWORDS,
    RESOURCE_KEYWORDS,
)
from core.async_utils import executor, run_async
from core.classifier import ClassificationResult, MessageClassifier
from core.db_ops import execute, insert_action_item
from core.formatter import format_capture_confirmation, format_error
from core.vault_ops import (
    append_to_daily_note,
    create_inbox_entry,
    ensure_dimension_pages,
    format_capture_line,
)

logger = logging.getLogger(__name__)

# Module-level classifier instance
_classifier = MessageClassifier()


def get_classifier() -> MessageClassifier:
    """Return the module-level classifier (for hot-swapping keywords)."""
    return _classifier


def _detect_project_mention(text: str) -> bool:
    """Check if text mentions project-related keywords."""
    text_lower = text.lower()
    return sum(1 for kw in PROJECT_KEYWORDS if kw in text_lower) >= 2


def _detect_resource_mention(text: str) -> bool:
    """Check if text mentions resource-related keywords."""
    text_lower = text.lower()
    return sum(1 for kw in RESOURCE_KEYWORDS if kw in text_lower) >= 2


def _log_classification(text: str, ts: str, result: ClassificationResult):
    """Log classification result to SQLite."""
    try:
        primary = result.matches[0].dimension if result.matches else None
        confidence = result.matches[0].confidence if result.matches else 0.0
        method = result.matches[0].method if result.matches else "none"
        all_scores = json.dumps([
            {"dimension": m.dimension, "confidence": m.confidence, "method": m.method}
            for m in result.matches
        ]) if result.matches else "[]"

        run_async(execute(
            "INSERT INTO classifications "
            "(message_text, message_ts, primary_dimension, confidence, method, all_scores_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (text, ts, primary, confidence, method, all_scores),
        ))
    except Exception:
        logger.exception("Failed to log classification")


def _build_feedback_buttons(ts: str, dimensions: list[str]) -> list[dict]:
    """Build Slack blocks with feedback buttons for classification correction."""
    dim_label = " + ".join(dimensions) if dimensions else "Uncategorized"
    return [
        {
            "type": "actions",
            "block_id": f"feedback_{ts}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Correct"},
                    "action_id": "feedback_correct",
                    "value": json.dumps({"ts": ts, "dimensions": dimensions}),
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Wrong"},
                    "action_id": "feedback_wrong",
                    "value": json.dumps({"ts": ts, "dimensions": dimensions}),
                    "style": "danger",
                },
            ],
        },
    ]


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

    # Classify via hybrid pipeline
    result = _classifier.classify(text)

    # Noise filter: greetings and small talk
    if result.is_noise:
        logger.info("Noise filtered: %r", text[:80])
        try:
            client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text="Hey! Drop a thought, idea, or task here and I'll route it to the right place.",
            )
        except Exception:
            logger.exception("Failed to send noise reply")
        return

    try:
        dimensions = [m.dimension for m in result.matches]
        confidence = result.matches[0].confidence if result.matches else 0.0
        method = result.matches[0].method if result.matches else "none"

        logger.info(
            "Classified %r: dims=%s confidence=%.2f method=%s (%.0fms)",
            text[:60], dimensions, confidence, method, result.execution_time_ms,
        )

        # --- Vault writes (ALL paths — classified or not) ---
        today = datetime.now().strftime("%Y-%m-%d")

        # Daily note with wikilinks
        capture_line = format_capture_line(
            text, dimensions=dimensions, is_action=result.is_actionable,
        )
        append_to_daily_note(today, capture_line, section="## Log")

        # Inbox entry with dimension frontmatter
        create_inbox_entry(
            text,
            source="slack",
            dimensions=dimensions,
            confidence=confidence,
            method=method,
        )

        # Action item dual-write (SQLite + daily note already handled above)
        if result.is_actionable:
            primary_dim = dimensions[0] if dimensions else None
            run_async(
                insert_action_item(
                    description=text,
                    source="slack-inbox",
                    icor_element=primary_dim,
                )
            )

        # Log classification to DB
        _log_classification(text, ts, result)

        # --- Slack routing (only if classified) ---
        target_channel_names = []
        if dimensions:
            for i, dim in enumerate(dimensions):
                ch_name = DIMENSION_CHANNELS.get(dim, "brain-systems")
                target_channel_names.append(ch_name)
                ch_id = channel_ids.get(ch_name)
                if not ch_id:
                    continue

                label = "Primary" if i == 0 else "Also relevant"
                client.chat_postMessage(
                    channel=ch_id,
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
                                    "text": (
                                        f"{label} | Routed from #brain-inbox | {today} | "
                                        f"{method} ({confidence:.0%})"
                                    ),
                                }
                            ],
                        },
                    ],
                )

        # Cross-post to PARA channels if keywords match
        primary_channel = target_channel_names[0] if target_channel_names else "brain-inbox"
        if _detect_project_mention(text):
            projects_ch = channel_ids.get("brain-projects")
            if projects_ch:
                client.chat_postMessage(
                    channel=projects_ch,
                    text="Project-related capture from inbox",
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
                                    "text": f"Cross-posted from #brain-inbox → #{primary_channel} | {today}",
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
                    text="Resource-related capture from inbox",
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
                                    "text": f"Cross-posted from #brain-inbox → #{primary_channel} | {today}",
                                }
                            ],
                        },
                    ],
                )

        # Reply in thread in #brain-inbox
        blocks = format_capture_confirmation(text, dimensions, target_channel_names)
        # Append feedback buttons
        blocks.extend(_build_feedback_buttons(ts, dimensions))

        summary_text = (
            f"Captured and routed to {', '.join('#' + c for c in target_channel_names)}"
            if target_channel_names
            else "Captured to inbox (uncategorized)"
        )
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=summary_text,
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

    # Ensure dimension wikilink targets exist in vault
    try:
        ensure_dimension_pages()
    except Exception:
        logger.exception("Failed to ensure dimension pages")

    # Channel IDs populated by app.py at startup
    _channel_ids: dict[str, str] = {}

    def set_channel_ids(ids: dict[str, str]):
        """Set channel ID cache (called from app.py at startup)."""
        _channel_ids.update(ids)

    # Expose setter on module for app.py to call
    register.set_channel_ids = set_channel_ids

    @app.event("message")
    def handle_message(event, client, say):
        """Handle messages -- route brain-inbox captures in background."""
        channel = event.get("channel", "")
        inbox_id = _channel_ids.get("brain-inbox")

        # Only process messages in #brain-inbox
        if not inbox_id or channel != inbox_id:
            return

        # Ignore bot messages and message_changed events
        if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            return

        # Process in background via shared thread pool
        executor.submit(_process_capture, client, event, _channel_ids)

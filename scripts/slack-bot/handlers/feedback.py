"""Feedback handlers for classification corrections.

Handles "Correct" / "Wrong" button clicks on routed messages.
Updates the classifications table and keyword_feedback for learning.
"""
import json
import logging

from slack_bolt import App

from config import DIMENSION_CHANNELS
from core.async_utils import run_async
from core.db_ops import execute

logger = logging.getLogger(__name__)


def register(app: App):
    """Register feedback action handlers."""

    @app.action("feedback_correct")
    def handle_correct(ack, body, client):
        """User confirmed the classification was correct."""
        ack()
        try:
            value = json.loads(body["actions"][0]["value"])
            ts = value.get("ts", "")
            dimensions = value.get("dimensions", [])

            # Increment success count for keywords that matched this dimension
            for dim in dimensions:
                run_async(execute(
                    "UPDATE keyword_feedback SET success_count = success_count + 1 "
                    "WHERE dimension = ?",
                    (dim,),
                ))

            # Update the message to show confirmed
            channel = body.get("channel", {}).get("id", "")
            message_ts = body.get("message", {}).get("ts", "")
            if channel and message_ts:
                # Remove buttons and add confirmation
                original_blocks = body.get("message", {}).get("blocks", [])
                # Filter out the feedback action block
                updated_blocks = [
                    b for b in original_blocks
                    if not (b.get("block_id", "").startswith("feedback_"))
                ]
                updated_blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "Classification confirmed"}],
                })
                client.chat_update(
                    channel=channel,
                    ts=message_ts,
                    blocks=updated_blocks,
                    text="Classification confirmed",
                )
        except Exception:
            logger.exception("Failed to handle feedback_correct")

    @app.action("feedback_wrong")
    def handle_wrong(ack, body, client):
        """User indicated the classification was wrong — show dimension picker."""
        ack()
        try:
            value = json.loads(body["actions"][0]["value"])
            ts = value.get("ts", "")
            original_dims = value.get("dimensions", [])

            # Build overflow menu with all dimensions
            options = [
                {
                    "text": {"type": "plain_text", "text": dim},
                    "value": json.dumps({
                        "ts": ts,
                        "correct_dimension": dim,
                        "original_dimensions": original_dims,
                    }),
                }
                for dim in DIMENSION_CHANNELS.keys()
            ]

            channel = body.get("channel", {}).get("id", "")
            message_ts = body.get("message", {}).get("ts", "")
            if channel and message_ts:
                original_blocks = body.get("message", {}).get("blocks", [])
                # Replace feedback buttons with dimension picker
                updated_blocks = [
                    b for b in original_blocks
                    if not (b.get("block_id", "").startswith("feedback_"))
                ]
                updated_blocks.append({
                    "type": "actions",
                    "block_id": f"correction_{ts}",
                    "elements": [
                        {
                            "type": "static_select",
                            "placeholder": {"type": "plain_text", "text": "Select correct dimension"},
                            "action_id": "feedback_select_dimension",
                            "options": options,
                        },
                    ],
                })
                client.chat_update(
                    channel=channel,
                    ts=message_ts,
                    blocks=updated_blocks,
                    text="Select the correct dimension",
                )
        except Exception:
            logger.exception("Failed to handle feedback_wrong")

    @app.action("feedback_select_dimension")
    def handle_dimension_select(ack, body, client):
        """User selected the correct dimension from the picker."""
        ack()
        try:
            selected = body["actions"][0]["selected_option"]["value"]
            data = json.loads(selected)
            ts = data.get("ts", "")
            correct_dim = data.get("correct_dimension", "")
            original_dims = data.get("original_dimensions", [])

            # Update classification record
            run_async(execute(
                "UPDATE classifications SET user_correction = ?, corrected_at = datetime('now') "
                "WHERE message_ts = ?",
                (correct_dim, ts),
            ))

            # Decrement success / increment fail for original dimensions
            for dim in original_dims:
                run_async(execute(
                    "UPDATE keyword_feedback SET fail_count = fail_count + 1 "
                    "WHERE dimension = ?",
                    (dim,),
                ))

            # Update the message
            channel = body.get("channel", {}).get("id", "")
            message_ts = body.get("message", {}).get("ts", "")
            if channel and message_ts:
                original_blocks = body.get("message", {}).get("blocks", [])
                updated_blocks = [
                    b for b in original_blocks
                    if not (b.get("block_id", "").startswith("correction_"))
                ]
                updated_blocks.append({
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f"Corrected to *{correct_dim}* (was: {', '.join(original_dims) or 'none'})",
                    }],
                })
                client.chat_update(
                    channel=channel,
                    ts=message_ts,
                    blocks=updated_blocks,
                    text=f"Corrected to {correct_dim}",
                )

            logger.info("Classification corrected: ts=%s, %s -> %s", ts, original_dims, correct_dim)
        except Exception:
            logger.exception("Failed to handle feedback_select_dimension")

"""Block Kit interactive action handlers."""
import asyncio
import json
import logging
from datetime import datetime

from slack_bolt import App

from core.db_ops import execute
from core.vault_ops import append_to_daily_note, create_inbox_entry

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def register(app: App):
    """Register all interactive action handlers."""

    @app.action("complete_action")
    def handle_complete(ack, action, client, body):
        """Mark an action item as completed."""
        ack()
        action_id = action.get("value", "")
        if not action_id:
            return

        try:
            _run_async(
                execute(
                    "UPDATE action_items SET status = 'completed', completed_at = datetime('now') WHERE id = ?",
                    (int(action_id),),
                )
            )

            # Update the original message to show completion
            channel = body["channel"]["id"]
            ts = body["message"]["ts"]
            client.chat_update(
                channel=channel,
                ts=ts,
                text="Action completed",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: *Action #{action_id} completed*",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Completed at {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                            }
                        ],
                    },
                ],
            )
        except Exception:
            logger.exception("Error completing action %s", action_id)

    @app.action("snooze_action")
    def handle_snooze(ack, action, client, body):
        """Snooze an action item by pushing it forward one day."""
        ack()
        action_id = action.get("value", "")
        if not action_id:
            return

        try:
            _run_async(
                execute(
                    "UPDATE action_items SET source_date = date(source_date, '+1 day') WHERE id = ?",
                    (int(action_id),),
                )
            )

            channel = body["channel"]["id"]
            ts = body["message"]["ts"]
            client.chat_update(
                channel=channel,
                ts=ts,
                text="Action snoozed",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":clock1: *Action #{action_id} snoozed to tomorrow*",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Snoozed at {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                            }
                        ],
                    },
                ],
            )
        except Exception:
            logger.exception("Error snoozing action %s", action_id)

    @app.action("delegate_action")
    def handle_delegate(ack, action, client, body):
        """Open a modal to delegate an action item."""
        ack()
        action_id = action.get("value", "")
        trigger_id = body.get("trigger_id", "")

        if not action_id or not trigger_id:
            return

        try:
            client.views_open(
                trigger_id=trigger_id,
                view={
                    "type": "modal",
                    "callback_id": "delegate_modal",
                    "private_metadata": json.dumps(
                        {
                            "action_id": action_id,
                            "channel": body["channel"]["id"],
                            "message_ts": body["message"]["ts"],
                        }
                    ),
                    "title": {"type": "plain_text", "text": "Delegate Action"},
                    "submit": {"type": "plain_text", "text": "Delegate"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "delegate_to",
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "delegate_name",
                                "placeholder": {
                                    "type": "plain_text",
                                    "text": "Who should handle this?",
                                },
                            },
                            "label": {"type": "plain_text", "text": "Delegate to"},
                        },
                        {
                            "type": "input",
                            "block_id": "delegate_notes",
                            "optional": True,
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "notes_input",
                                "multiline": True,
                                "placeholder": {
                                    "type": "plain_text",
                                    "text": "Any notes for the delegate?",
                                },
                            },
                            "label": {"type": "plain_text", "text": "Notes"},
                        },
                    ],
                },
            )
        except Exception:
            logger.exception("Error opening delegate modal for action %s", action_id)

    @app.view("delegate_modal")
    def handle_delegate_submit(ack, view, client):
        """Process the delegate modal submission."""
        ack()
        meta = json.loads(view.get("private_metadata", "{}"))
        action_id = meta.get("action_id", "")
        channel = meta.get("channel", "")
        message_ts = meta.get("message_ts", "")

        values = view["state"]["values"]
        delegate_name = values["delegate_to"]["delegate_name"]["value"]
        notes = values["delegate_notes"]["notes_input"].get("value", "")

        try:
            _run_async(
                execute(
                    "UPDATE action_items SET status = 'delegated', delegated_to = ? WHERE id = ?",
                    (delegate_name, int(action_id)),
                )
            )

            if channel and message_ts:
                note_text = f"\nNotes: {notes}" if notes else ""
                client.chat_update(
                    channel=channel,
                    ts=message_ts,
                    text=f"Action delegated to {delegate_name}",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f":handshake: *Action #{action_id} delegated to {delegate_name}*"
                                    f"{note_text}"
                                ),
                            },
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Delegated at {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                                }
                            ],
                        },
                    ],
                )
        except Exception:
            logger.exception("Error delegating action %s", action_id)

    @app.action("save_to_vault")
    def handle_save_to_vault(ack, action, client, body):
        """Save a generated report or idea to the vault."""
        ack()
        try:
            payload = json.loads(action.get("value", "{}"))
            command = payload.get("command", "report")
            content = payload.get("content", "")

            if not content:
                return

            # Save as inbox entry with the command as source
            create_inbox_entry(content, source=f"slack-{command}")

            # Also append a reference to today's daily note
            today = datetime.now().strftime("%Y-%m-%d")
            append_to_daily_note(
                today,
                f"- Saved /{command} report to vault inbox",
                section="## Log",
            )

            # Update the message to confirm save
            channel = body["channel"]["id"]
            ts = body["message"]["ts"]
            original_blocks = body["message"].get("blocks", [])

            # Replace the actions block with a confirmation
            updated_blocks = [
                b for b in original_blocks if b.get("type") != "actions"
            ]
            updated_blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":floppy_disk: Saved to vault at {datetime.now().strftime('%H:%M')}",
                        }
                    ],
                }
            )

            client.chat_update(
                channel=channel,
                ts=ts,
                text="Report saved to vault",
                blocks=updated_blocks,
            )
        except Exception:
            logger.exception("Error saving to vault")

    @app.action("dismiss")
    def handle_dismiss(ack, action, client, body):
        """Remove an interactive message."""
        ack()
        try:
            channel = body["channel"]["id"]
            ts = body["message"]["ts"]
            client.chat_delete(channel=channel, ts=ts)
        except Exception:
            logger.exception("Error dismissing message")

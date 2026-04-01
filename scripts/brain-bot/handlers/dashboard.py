"""Dashboard command handler and pinned message updater for Telegram.

Replaces Slack's App Home tab with:
- /dashboard command: sends the full 8-section dashboard
- Pinned message: compact summary updated on schedule
- Quick action buttons: trigger corresponding commands
- Alert dismiss + action complete/snooze buttons
"""
import json
import logging

from telegram import Bot, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import GROUP_CHAT_ID, TOPICS
from core.dashboard_builder import build_dashboard_view, build_pinned_summary
from core.message_utils import send_long_message

logger = logging.getLogger(__name__)

# Store pinned message ID for updates (persisted in bot_data by PTB)
_PINNED_MSG_KEY = "dashboard_pinned_msg_id"


# ---------------------------------------------------------------------------
# /dashboard command
# ---------------------------------------------------------------------------

async def _handle_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /dashboard command — send full dashboard to user."""
    try:
        html, keyboard = build_dashboard_view()
        await send_long_message(
            context.bot,
            chat_id=update.effective_chat.id,
            text=html,
            reply_markup=keyboard,
            topic_id=getattr(update.message, "message_thread_id", None),
        )
    except Exception:
        logger.exception("Failed to send dashboard")
        await update.message.reply_text("\u274c Failed to build dashboard. Check bot logs.")


# ---------------------------------------------------------------------------
# Pinned message management
# ---------------------------------------------------------------------------

async def update_pinned_dashboard(bot: Bot) -> None:
    """Update (or create) the pinned dashboard summary in the dashboard topic.

    Called by the dashboard_refresh scheduled job.
    """
    topic_id = TOPICS.get("brain-dashboard")
    if not topic_id:
        logger.debug("brain-dashboard topic not configured, skipping pinned update")
        return

    html = build_pinned_summary()

    # Try to edit existing pinned message
    # We store the message ID in a file since bot_data isn't accessible here
    pinned_msg_id = _load_pinned_msg_id()

    if pinned_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=GROUP_CHAT_ID,
                message_id=pinned_msg_id,
                text=html,
                parse_mode="HTML",
            )
            logger.debug("Pinned dashboard updated (msg_id=%d)", pinned_msg_id)
            return
        except Exception:
            logger.debug("Could not edit pinned message %d, will create new", pinned_msg_id)

    # Create new pinned message
    try:
        msg = await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=topic_id,
            text=html,
            parse_mode="HTML",
        )
        try:
            await bot.pin_chat_message(
                chat_id=GROUP_CHAT_ID,
                message_id=msg.message_id,
                disable_notification=True,
            )
        except Exception:
            logger.debug("Could not pin message (may need admin rights)")

        _save_pinned_msg_id(msg.message_id)
        logger.info("Created and pinned new dashboard message (msg_id=%d)", msg.message_id)
    except Exception:
        logger.exception("Failed to create pinned dashboard message")


def _load_pinned_msg_id() -> int | None:
    """Load pinned message ID from disk."""
    try:
        from config import DB_PATH
        from pathlib import Path
        state_file = Path(DB_PATH).parent / ".dashboard_pinned_id"
        if state_file.exists():
            return int(state_file.read_text().strip())
    except Exception:
        pass
    return None


def _save_pinned_msg_id(msg_id: int) -> None:
    """Persist pinned message ID to disk."""
    try:
        from config import DB_PATH
        from pathlib import Path
        state_file = Path(DB_PATH).parent / ".dashboard_pinned_id"
        state_file.write_text(str(msg_id))
    except Exception:
        logger.debug("Could not save pinned message ID", exc_info=True)


# ---------------------------------------------------------------------------
# Quick action button callbacks
# ---------------------------------------------------------------------------

async def _handle_quick_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quick action buttons from dashboard keyboard."""
    cq = update.callback_query
    await cq.answer()

    try:
        data = json.loads(cq.data)
    except (json.JSONDecodeError, TypeError):
        return

    cmd = data.get("cmd")
    if not cmd:
        return

    # Map button commands to handler functions
    _CMD_MAP = {
        "today": "today",
        "close": "close-day",
        "drift": "drift",
        "ideas": "ideas",
        "find": "find",
        "sync": "sync",
    }

    brain_cmd = _CMD_MAP.get(cmd)
    if not brain_cmd:
        return

    # Notify user that the command is running
    await cq.edit_message_reply_markup(reply_markup=None)

    try:
        # Import and delegate to the commands handler
        from handlers.commands import run_command_from_callback
        await run_command_from_callback(
            bot=context.bot,
            chat_id=cq.message.chat_id,
            topic_id=getattr(cq.message, "message_thread_id", None),
            command=brain_cmd,
            user_input="",
        )
    except ImportError:
        logger.warning("commands.run_command_from_callback not available")
        await context.bot.send_message(
            chat_id=cq.message.chat_id,
            text=f"Running /{brain_cmd}... (command handler not yet migrated)",
            message_thread_id=getattr(cq.message, "message_thread_id", None),
        )
    except Exception:
        logger.exception("Quick action %s failed", cmd)


# ---------------------------------------------------------------------------
# Alert dismiss callback
# ---------------------------------------------------------------------------

async def _handle_dismiss_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle alert dismiss buttons."""
    cq = update.callback_query
    await cq.answer()

    try:
        data = json.loads(cq.data)
    except (json.JSONDecodeError, TypeError):
        return

    if data.get("a") != "dismiss_alert":
        return

    alert_id = data.get("id")
    if not alert_id:
        return

    try:
        from core.db_ops import execute
        await execute(
            "UPDATE alerts SET status = 'dismissed', dismissed_at = datetime('now') "
            "WHERE id = ? AND status = 'active'",
            (int(alert_id),),
        )
        await cq.edit_message_text(
            text=cq.message.text_html + "\n\n<i>\u2705 Alert dismissed</i>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error dismissing alert %s", alert_id)


# ---------------------------------------------------------------------------
# Action complete/snooze callbacks
# ---------------------------------------------------------------------------

async def _handle_dash_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle complete/snooze buttons from dashboard pending actions."""
    cq = update.callback_query
    await cq.answer()

    try:
        data = json.loads(cq.data)
    except (json.JSONDecodeError, TypeError):
        return

    action_type = data.get("a")
    action_id = data.get("id")
    if not action_id or action_type not in ("dash_complete", "dash_snooze"):
        return

    try:
        from core.db_ops import execute
        if action_type == "dash_complete":
            await execute(
                "UPDATE action_items SET status = 'completed', completed_at = datetime('now') WHERE id = ?",
                (int(action_id),),
            )
            label = "\u2705 Completed"
        else:
            await execute(
                "UPDATE action_items SET source_date = date(source_date, '+1 day') WHERE id = ?",
                (int(action_id),),
            )
            label = "\u23f0 Snoozed"

        # Update the message to show result
        try:
            current_text = cq.message.text_html or cq.message.text or ""
            await cq.edit_message_text(
                text=current_text + f"\n\n<i>{label}</i>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    except Exception:
        logger.exception("Error handling dash action %s for id %s", action_type, action_id)


# ---------------------------------------------------------------------------
# Callback query filter
# ---------------------------------------------------------------------------

def _is_dashboard_callback(data: str) -> bool:
    """Check if callback data is from a dashboard button."""
    try:
        parsed = json.loads(data)
        return (
            "cmd" in parsed
            or parsed.get("a") in ("dismiss_alert", "dash_complete", "dash_snooze")
        )
    except (json.JSONDecodeError, TypeError):
        return False


def _match_quick_action(data: object) -> bool:
    """Pattern filter for quick action callbacks (cmd key in JSON)."""
    if not isinstance(data, str):
        return False
    try:
        parsed = json.loads(data)
        return "cmd" in parsed
    except (json.JSONDecodeError, TypeError):
        return False


def _match_alert_dismiss(data: object) -> bool:
    """Pattern filter for alert dismiss callbacks."""
    if not isinstance(data, str):
        return False
    try:
        parsed = json.loads(data)
        return parsed.get("a") == "dismiss_alert"
    except (json.JSONDecodeError, TypeError):
        return False


def _match_dash_action(data: object) -> bool:
    """Pattern filter for dashboard complete/snooze callbacks."""
    if not isinstance(data, str):
        return False
    try:
        parsed = json.loads(data)
        return parsed.get("a") in ("dash_complete", "dash_snooze")
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(application: Application):
    """Register dashboard command and callback query handlers."""

    # /dashboard command
    application.add_handler(CommandHandler("dashboard", _handle_dashboard), group=1)

    # Quick action buttons (cmd key in callback data)
    application.add_handler(
        CallbackQueryHandler(_handle_quick_action, pattern=_match_quick_action),
        group=2,
    )

    # Alert dismiss buttons
    application.add_handler(
        CallbackQueryHandler(_handle_dismiss_alert, pattern=_match_alert_dismiss),
        group=2,
    )

    # Dashboard action complete/snooze buttons
    application.add_handler(
        CallbackQueryHandler(_handle_dash_action, pattern=_match_dash_action),
        group=2,
    )

    logger.info("Dashboard handlers registered")

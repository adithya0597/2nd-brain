"""Interactive action handlers for Telegram (CallbackQuery + ConversationHandler).

Handles Complete/Snooze/Delegate buttons on action items, Save-to-Vault
buttons on reports, and Dismiss buttons.
"""
import json
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.async_utils import run_in_executor
from core.db_ops import execute
from core.vault_ops import create_report_file

logger = logging.getLogger(__name__)

# ConversationHandler states for delegate flow
DELEGATE_NAME, DELEGATE_NOTES = range(2)


async def handle_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark an action item as completed."""
    query = update.callback_query
    await query.answer("\u2705 Completed!")

    data = json.loads(query.data)
    action_id = data.get("id", "")
    if not action_id:
        return

    try:
        await execute(
            "UPDATE action_items SET status = 'completed', completed_at = datetime('now') WHERE id = ?",
            (int(action_id),),
        )

        await query.edit_message_text(
            f"\u2705 <b>Action #{action_id} completed</b>\n"
            f"<i>Completed at {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error completing action %s", action_id)


async def handle_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Snooze an action item by pushing it forward one day."""
    query = update.callback_query
    await query.answer("\u23f0 Snoozed!")

    data = json.loads(query.data)
    action_id = data.get("id", "")
    if not action_id:
        return

    try:
        await execute(
            "UPDATE action_items SET source_date = date(source_date, '+1 day') WHERE id = ?",
            (int(action_id),),
        )

        await query.edit_message_text(
            f"\u23f0 <b>Action #{action_id} snoozed to tomorrow</b>\n"
            f"<i>Snoozed at {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Error snoozing action %s", action_id)


async def handle_delegate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the delegate conversation: ask for delegate name."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    action_id = data.get("id", "")
    if not action_id:
        return ConversationHandler.END

    # Store context for the conversation
    context.user_data["delegate_action_id"] = action_id
    context.user_data["delegate_query_message"] = query.message

    await query.message.reply_text("Who should handle this action?")
    return DELEGATE_NAME


async def receive_delegate_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive the delegate name, ask for notes."""
    context.user_data["delegate_name"] = update.message.text
    await update.message.reply_text(
        "Any notes for the delegate? (type notes or /skip)"
    )
    return DELEGATE_NOTES


async def receive_delegate_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive notes and finalize delegation."""
    notes = update.message.text
    name = context.user_data.pop("delegate_name", "")
    action_id = context.user_data.pop("delegate_action_id", "")
    original_msg = context.user_data.pop("delegate_query_message", None)

    if not action_id or not name:
        await update.message.reply_text("\u274c Delegation cancelled (missing data).")
        return ConversationHandler.END

    try:
        await execute(
            "UPDATE action_items SET status = 'delegated', delegated_to = ? WHERE id = ?",
            (name, int(action_id)),
        )

        import html
        safe_name = html.escape(name)
        note_text = f"\nNotes: {html.escape(notes)}" if notes else ""

        # Update the original action message
        if original_msg:
            try:
                await original_msg.edit_text(
                    f"\U0001f4e4 <b>Action #{action_id} delegated to {safe_name}</b>"
                    f"{note_text}\n"
                    f"<i>Delegated at {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await update.message.reply_text(f"\u2705 Delegated to {safe_name}")

    except Exception:
        logger.exception("Error delegating action %s", action_id)
        await update.message.reply_text("\u274c Failed to delegate. Check bot logs.")

    return ConversationHandler.END


async def skip_delegate_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip notes and finalize delegation with empty notes."""
    # Reuse receive_delegate_notes with empty text override
    update.message.text = ""
    return await receive_delegate_notes(update, context)


async def cancel_delegate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the delegate conversation."""
    context.user_data.pop("delegate_action_id", None)
    context.user_data.pop("delegate_name", None)
    context.user_data.pop("delegate_query_message", None)
    await update.message.reply_text("Delegation cancelled.")
    return ConversationHandler.END


async def handle_save_vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a report to the vault."""
    query = update.callback_query
    await query.answer("\U0001f4be Saving...")

    try:
        data = json.loads(query.data)
        command = data.get("cmd", "report")

        # Use the message's plain text as content
        content = query.message.text or ""
        if not content:
            return

        await run_in_executor(create_report_file, command, content)

        # Remove the save button
        await query.edit_message_reply_markup(reply_markup=None)

        # Notify
        await query.message.reply_text(
            f"\U0001f4be Saved to vault at {datetime.now().strftime('%H:%M')}",
        )
    except Exception:
        logger.exception("Error saving to vault")


async def handle_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete an interactive message."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        logger.exception("Error dismissing message")


def register(application: Application):
    """Register all interactive action handlers."""

    # Delegate conversation (must be registered before individual callback handlers)
    delegate_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_delegate_start, pattern=r'\{"a":"delegate"'),
        ],
        states={
            DELEGATE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delegate_name),
            ],
            DELEGATE_NOTES: [
                CommandHandler("skip", skip_delegate_notes),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delegate_notes),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_delegate)],
        per_message=False,
    )
    application.add_handler(delegate_conv)

    # Simple callback query handlers
    application.add_handler(CallbackQueryHandler(handle_complete, pattern=r'\{"a":"complete"'))
    application.add_handler(CallbackQueryHandler(handle_snooze, pattern=r'\{"a":"snooze"'))
    application.add_handler(CallbackQueryHandler(handle_save_vault, pattern=r'\{"a":"save_vault"'))
    application.add_handler(CallbackQueryHandler(handle_dismiss, pattern=r'\{"a":"dismiss"'))

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


async def handle_review_fading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a preview of the top fading file."""
    cb = update.callback_query
    await cb.answer("Loading...")

    try:
        from core.db_ops import query as _query
        fading = await _query("""
            SELECT n.title, n.file_path
            FROM vault_nodes n
            LEFT JOIN vault_edges e ON n.id = e.source_node_id
            WHERE n.node_type = 'document'
              AND n.file_path NOT LIKE '%Daily Notes%'
              AND n.file_path NOT LIKE '%Inbox%'
              AND n.file_path NOT LIKE '%Reports%'
              AND NOT EXISTS (
                  SELECT 1 FROM vault_edges re
                  JOIN vault_nodes src ON re.source_node_id = src.id
                  WHERE re.target_node_id = n.id
                    AND re.edge_type = 'wikilink'
                    AND src.last_modified >= date('now', '-30 days')
              )
            GROUP BY n.id HAVING COUNT(e.id) >= 3
            ORDER BY julianday('now') - julianday(n.indexed_at) DESC
            LIMIT 1
        """)

        if fading:
            import config
            file_path = config.VAULT_PATH / fading[0]["file_path"]
            title = fading[0]["title"]
            content = ""
            if file_path.exists():
                content = file_path.read_text()[:500]

            from core.formatter import _esc
            await cb.message.reply_text(
                f"<b>\U0001f4d6 {_esc(title)}</b>\n\n"
                f"<blockquote>{_esc(content)}{'...' if len(content) >= 500 else ''}</blockquote>",
                parse_mode="HTML",
            )
        else:
            await cb.message.reply_text("No fading content found.")
    except Exception:
        logger.exception("Review fading failed")
        await cb.message.reply_text("Failed to load content.")


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
    application.add_handler(CallbackQueryHandler(handle_review_fading, pattern=r'\{"a":"review_fading"'))

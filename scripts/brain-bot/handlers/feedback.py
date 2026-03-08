"""Classification feedback handlers for Telegram.

Handles Correct/Wrong button clicks on capture confirmations.
Updates the classifications table and keyword_feedback for learning.
"""
import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import config
from config import DIMENSION_TOPICS
from core.db_ops import execute, query

logger = logging.getLogger(__name__)


def _cb(data: dict) -> str:
    """Compact JSON callback data."""
    return json.dumps(data, separators=(",", ":"))


async def handle_fb_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmed the classification was correct."""
    cb_query = update.callback_query
    await cb_query.answer("\u2705 Thanks!")

    try:
        data = json.loads(cb_query.data)
        msg_id = data.get("m", "")

        # Look up dimensions from the classification record
        rows = await query(
            "SELECT primary_dimension, all_scores_json FROM classifications WHERE message_ts = ?",
            (str(msg_id),),
        )
        if rows:
            primary_dim = rows[0]["primary_dimension"]
            if primary_dim:
                await execute(
                    "UPDATE keyword_feedback SET success_count = success_count + 1 "
                    "WHERE dimension = ?",
                    (primary_dim,),
                )

        # Update the message: remove buttons, add confirmation
        await cb_query.edit_message_reply_markup(reply_markup=None)
        original_text = cb_query.message.text_html or cb_query.message.text or ""
        await cb_query.edit_message_text(
            original_text + "\n\n<i>\u2705 Classification confirmed</i>",
            parse_mode="HTML",
        )

    except Exception:
        logger.exception("Failed to handle feedback_correct")


async def handle_fb_wrong(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User indicated the classification was wrong — show dimension picker."""
    cb_query = update.callback_query
    await cb_query.answer()

    try:
        data = json.loads(cb_query.data)
        msg_id = data.get("m", "")

        # Build dimension picker (2 per row)
        dim_names = list(DIMENSION_TOPICS.keys())
        buttons = [
            InlineKeyboardButton(
                dim_name,
                callback_data=_cb({"a": "fb_d", "m": msg_id, "d": i}),
            )
            for i, dim_name in enumerate(dim_names)
        ]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        keyboard = InlineKeyboardMarkup(rows)

        # Replace buttons with dimension picker
        original_text = cb_query.message.text_html or cb_query.message.text or ""
        await cb_query.edit_message_text(
            original_text + "\n\n<b>Select the correct dimension:</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        logger.exception("Failed to handle feedback_wrong")


async def handle_fb_dim_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected the correct dimension from the picker."""
    cb_query = update.callback_query
    await cb_query.answer()

    try:
        data = json.loads(cb_query.data)
        msg_id = data.get("m", "")
        dim_idx = data.get("d", 0)

        dim_names = list(DIMENSION_TOPICS.keys())
        if dim_idx < 0 or dim_idx >= len(dim_names):
            return
        correct_dim = dim_names[dim_idx]

        # Look up original dimensions
        rows = await query(
            "SELECT primary_dimension, all_scores_json FROM classifications WHERE message_ts = ?",
            (str(msg_id),),
        )
        original_dims = []
        if rows:
            original_dim = rows[0]["primary_dimension"]
            if original_dim:
                original_dims = [original_dim]
            # Also try to get all from scores JSON
            try:
                scores = json.loads(rows[0]["all_scores_json"] or "[]")
                original_dims = [s["dimension"] for s in scores]
            except Exception:
                pass

        # Update classification record
        await execute(
            "UPDATE classifications SET user_correction = ?, corrected_at = datetime('now') "
            "WHERE message_ts = ?",
            (correct_dim, str(msg_id)),
        )

        # Decrement success / increment fail for original dimensions
        for dim in original_dims:
            await execute(
                "UPDATE keyword_feedback SET fail_count = fail_count + 1 "
                "WHERE dimension = ?",
                (dim,),
            )

        # Log corrected capture to captures_log
        if rows:
            text = rows[0].get("message_text", "") if isinstance(rows[0], dict) else ""
            if not text:
                text_rows = await query(
                    "SELECT message_text FROM classifications WHERE message_ts = ?",
                    (str(msg_id),),
                )
                text = text_rows[0]["message_text"] if text_rows else ""
            if text:
                await execute(
                    "INSERT INTO captures_log "
                    "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
                    "VALUES (?, ?, 1.0, 'user_corrected', 0, 'brain-inbox')",
                    (text, json.dumps([correct_dim])),
                )

        # Update the message
        import html
        original_text_parts = (cb_query.message.text or "").split("\nSelect the correct dimension:")
        base_text = original_text_parts[0].strip() if original_text_parts else ""

        orig_text = ", ".join(original_dims) or "none"
        await cb_query.edit_message_text(
            f"{html.escape(base_text)}\n\n"
            f"<i>Corrected to <b>{html.escape(correct_dim)}</b> "
            f"(was: {html.escape(orig_text)})</i>",
            parse_mode="HTML",
        )

        logger.info("Classification corrected: msg_id=%s, %s -> %s", msg_id, original_dims, correct_dim)

    except Exception:
        logger.exception("Failed to handle feedback_select_dimension")


async def handle_bouncer_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected a dimension from the confidence bouncer DM."""
    cb_query = update.callback_query
    await cb_query.answer()

    try:
        data = json.loads(cb_query.data)
        msg_id = data.get("m", "")
        dim_idx = data.get("d", 0)

        dim_names = list(DIMENSION_TOPICS.keys())
        if dim_idx < 0 or dim_idx >= len(dim_names):
            return
        selected_dim = dim_names[dim_idx]

        # Update pending_captures
        await execute(
            "UPDATE pending_captures SET user_selection = ?, status = 'resolved', "
            "resolved_at = datetime('now') WHERE message_ts = ?",
            (selected_dim, str(msg_id)),
        )

        # Update the bouncer DM message
        import html
        await cb_query.edit_message_text(
            f"\u2705 <b>Filed to {html.escape(selected_dim)}</b>",
            parse_mode="HTML",
        )

        # Look up original text for routing
        rows = await query(
            "SELECT message_text FROM pending_captures WHERE message_ts = ?",
            (str(msg_id),),
        )
        original_text = rows[0]["message_text"] if rows else ""

        # Complete the routing
        from handlers.capture import process_bouncer_resolution
        await process_bouncer_resolution(original_text, int(msg_id), selected_dim, None)

        logger.info("Bouncer resolved: msg_id=%s -> %s", msg_id, selected_dim)

    except Exception:
        logger.exception("Error handling bouncer selection")


def register(application: Application):
    """Register feedback callback query handlers."""
    application.add_handler(CallbackQueryHandler(handle_fb_correct, pattern=r'\{"a":"fb_ok"'))
    application.add_handler(CallbackQueryHandler(handle_fb_wrong, pattern=r'\{"a":"fb_no"'))
    application.add_handler(CallbackQueryHandler(handle_fb_dim_select, pattern=r'\{"a":"fb_d"'))
    application.add_handler(CallbackQueryHandler(handle_bouncer_select, pattern=r'\{"a":"bnc"'))

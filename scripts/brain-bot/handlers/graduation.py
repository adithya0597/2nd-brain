"""Telegram handlers for concept graduation proposals.

Handles Approve/Reject/Snooze/Edit Name buttons on graduation proposals.
Uses ConversationHandler for the Edit Name flow (same pattern as
handlers/actions.py delegate flow).
"""
import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from core.db_ops import execute, insert_concept_metadata, query
from core.formatter import _DIV, _cb, _esc
from core.vault_ops import create_concept_file

logger = logging.getLogger(__name__)

# ConversationHandler state for edit name flow
GC_EDIT_NAME = 0


# ---------------------------------------------------------------------------
# Proposal formatting
# ---------------------------------------------------------------------------


def format_graduation_proposal(proposal: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Format a single graduation proposal for Telegram."""
    pid = proposal["id"]
    title = _esc(proposal.get("proposed_title", "Untitled"))
    dim = _esc(proposal.get("proposed_dimension", ""))
    count = proposal.get("capture_count", 0)
    days = proposal.get("days_span", 0)
    texts = json.loads(proposal.get("source_texts", "[]"))

    source_lines = "\n".join(
        f'{i+1}. "{_esc(t[:100])}{"..." if len(t) > 100 else ""}"'
        for i, t in enumerate(texts[:5])
    )

    text = (
        f"<b>\U0001f393 Concept Graduation Proposal</b>"
        f"{_DIV}"
        f"<b>Proposed Concept:</b> {title}\n"
        f"<b>Dimension:</b> {dim}\n"
        f"<b>Evidence:</b> {count} captures over {days} days\n\n"
        f"<b>Source Captures:</b>\n"
        f"<blockquote>{source_lines}</blockquote>\n\n"
        f"<i>Auto-expires in 14 days</i>"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "\u2705 Approve",
                callback_data=_cb({"a": "gc_approve", "p": pid}),
            ),
            InlineKeyboardButton(
                "\u270f\ufe0f Edit Name",
                callback_data=_cb({"a": "gc_edit", "p": pid}),
            ),
        ],
        [
            InlineKeyboardButton(
                "\u274c Reject",
                callback_data=_cb({"a": "gc_reject", "p": pid}),
            ),
            InlineKeyboardButton(
                "\U0001f4a4 Not Now",
                callback_data=_cb({"a": "gc_snooze", "p": pid}),
            ),
        ],
    ])
    return text, kb


# ---------------------------------------------------------------------------
# Shared helper: create concept from proposal
# ---------------------------------------------------------------------------


async def _graduate_proposal(proposal: dict, title: str) -> str:
    """Create a concept file + metadata from a graduation proposal.

    Returns the relative vault path on success, or raises on failure.
    """
    dim = proposal.get("proposed_dimension", "")
    source_ids = json.loads(proposal.get("source_capture_ids", "[]"))

    file_path = create_concept_file(
        name=title,
        summary=f"Graduated from {len(source_ids)} captures about {dim}.",
        source_notes=[],
        icor_elements=[dim] if dim else [],
        status="seedling",
    )

    rel_path = str(file_path.relative_to(config.VAULT_PATH))
    await insert_concept_metadata(
        title=title,
        file_path=rel_path,
        icor_elements=[dim] if dim else [],
        first_mentioned="",
        last_mentioned="",
        mention_count=len(source_ids),
        summary=f"Graduated concept about {dim}.",
        status="seedling",
    )

    await execute(
        "UPDATE graduation_proposals SET status='approved', resolved_at=datetime('now') WHERE id=?",
        (proposal["id"],),
    )
    return rel_path


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


async def handle_gc_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve a graduation proposal -- create concept file."""
    cb = update.callback_query
    await cb.answer("Creating concept...")
    data = json.loads(cb.data)
    pid = data.get("p")

    rows = await query("SELECT * FROM graduation_proposals WHERE id = ?", (pid,))
    if not rows:
        await cb.edit_message_text("\u274c Proposal not found.")
        return

    proposal = rows[0]
    title = proposal["proposed_title"]
    dim = proposal.get("proposed_dimension", "")

    try:
        await _graduate_proposal(proposal, title)
        await cb.edit_message_text(
            f"<b>\U0001f393 Concept Graduated: {_esc(title)}</b>\n\n"
            f"\u2705 Created in vault/Concepts/\n"
            f"<i>Dimension: {_esc(dim)} | Status: seedling</i>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to graduate concept %s", title)
        await cb.edit_message_text(f"\u274c Failed to graduate: {_esc(title)}")


async def handle_gc_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject a graduation proposal permanently."""
    cb = update.callback_query
    await cb.answer("Rejected")
    data = json.loads(cb.data)
    pid = data.get("p")

    await execute(
        "UPDATE graduation_proposals SET status='rejected', resolved_at=datetime('now') WHERE id=?",
        (pid,),
    )

    rows = await query("SELECT proposed_title FROM graduation_proposals WHERE id=?", (pid,))
    title = rows[0]["proposed_title"] if rows else "?"

    await cb.edit_message_text(
        f"<b>\U0001f393 Proposal Rejected</b>\n\n"
        f"<s>{_esc(title)}</s>\n"
        f"<i>This cluster will not be proposed again.</i>",
        parse_mode="HTML",
    )


async def handle_gc_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Snooze a proposal for 7 days."""
    cb = update.callback_query
    await cb.answer("Snoozed for 7 days")
    data = json.loads(cb.data)
    pid = data.get("p")

    await execute(
        "UPDATE graduation_proposals SET status='snoozed', "
        "snooze_until=datetime('now','+7 days') WHERE id=?",
        (pid,),
    )

    await cb.edit_message_text(
        "<b>\U0001f4a4 Proposal Snoozed</b>\n"
        "<i>Will re-evaluate in 7 days.</i>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Edit Name ConversationHandler
# ---------------------------------------------------------------------------


async def handle_gc_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the edit-name flow for a graduation proposal."""
    cb = update.callback_query
    await cb.answer()
    data = json.loads(cb.data)
    context.user_data["gc_edit_pid"] = data.get("p")
    await cb.message.reply_text("Type the new concept name (or /cancel):")
    return GC_EDIT_NAME


async def receive_gc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive the new name and auto-approve the proposal."""
    new_name = update.message.text.strip()
    pid = context.user_data.get("gc_edit_pid")
    if not pid or not new_name:
        return ConversationHandler.END

    await execute(
        "UPDATE graduation_proposals SET proposed_title=? WHERE id=?",
        (new_name, pid),
    )

    rows = await query("SELECT * FROM graduation_proposals WHERE id=?", (pid,))
    if rows:
        proposal = rows[0]
        try:
            await _graduate_proposal(proposal, new_name)
            await update.message.reply_text(
                f"\u2705 <b>Concept Graduated: {_esc(new_name)}</b>",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to graduate renamed concept")
            await update.message.reply_text("\u274c Failed to create concept.")

    context.user_data.pop("gc_edit_pid", None)
    return ConversationHandler.END


async def cancel_gc_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the edit-name flow."""
    context.user_data.pop("gc_edit_pid", None)
    await update.message.reply_text("Edit cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(application):
    """Register graduation proposal handlers."""
    # ConversationHandler must be registered before individual callback handlers
    gc_edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_gc_edit_start, pattern=r'\{"a":"gc_edit"'),
        ],
        states={
            GC_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gc_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_gc_edit)],
        per_message=False,
    )
    application.add_handler(gc_edit_conv)
    application.add_handler(
        CallbackQueryHandler(handle_gc_approve, pattern=r'\{"a":"gc_approve"')
    )
    application.add_handler(
        CallbackQueryHandler(handle_gc_reject, pattern=r'\{"a":"gc_reject"')
    )
    application.add_handler(
        CallbackQueryHandler(handle_gc_snooze, pattern=r'\{"a":"gc_snooze"')
    )

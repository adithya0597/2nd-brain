"""Inbox message capture and routing handler for Telegram.

Listens for text messages (in the inbox topic if configured), classifies
the ICOR dimension, saves to vault + SQLite, and replies with confirmation
and feedback buttons.
"""
import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import config
from config import (
    DIMENSION_TOPICS,
    GROUP_CHAT_ID,
    OWNER_TELEGRAM_ID,
    PROJECT_KEYWORDS,
    RESOURCE_KEYWORDS,
    TOPICS,
)
from core.async_utils import run_in_executor
from core.classifier import ClassificationResult, MessageClassifier
from core.db_ops import execute, insert_action_item
from core.formatter import format_capture_confirmation, format_error
from core.message_utils import send_long_message
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
    text_lower = text.lower()
    return sum(1 for kw in PROJECT_KEYWORDS if kw in text_lower) >= 2


def _detect_resource_mention(text: str) -> bool:
    text_lower = text.lower()
    return sum(1 for kw in RESOURCE_KEYWORDS if kw in text_lower) >= 2


def _cb(data: dict) -> str:
    """Compact JSON callback data."""
    return json.dumps(data, separators=(",", ":"))


async def _log_classification(text: str, msg_id: int, result: ClassificationResult):
    """Log classification result to SQLite."""
    try:
        primary = result.matches[0].dimension if result.matches else None
        confidence = result.matches[0].confidence if result.matches else 0.0
        method = result.matches[0].method if result.matches else "none"
        all_scores = json.dumps([
            {"dimension": m.dimension, "confidence": m.confidence, "method": m.method}
            for m in result.matches
        ]) if result.matches else "[]"

        await execute(
            "INSERT INTO classifications "
            "(message_text, message_ts, primary_dimension, confidence, method, all_scores_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (text, str(msg_id), primary, confidence, method, all_scores),
        )
    except Exception:
        logger.exception("Failed to log classification")


async def _handle_low_confidence(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    result: ClassificationResult,
):
    """Route low-confidence captures to a DM with dimension picker."""
    text = update.message.text
    msg_id = update.message.message_id

    try:
        # Still save to daily note and inbox (unrouted)
        today = datetime.now().strftime("%Y-%m-%d")
        capture_line = format_capture_line(text, dimensions=[], is_action=result.is_actionable)
        await run_in_executor(append_to_daily_note, today, capture_line, section="## Log")
        await run_in_executor(
            create_inbox_entry, text, source="telegram", dimensions=[],
            confidence=result.matches[0].confidence, method="pending_clarification",
        )

        await _log_classification(text, msg_id, result)

        dimensions = [m.dimension for m in result.matches]
        confidence = result.matches[0].confidence
        method = result.matches[0].method

        scores_text = "\n".join(
            f"  {m.dimension} \u2014 {m.confidence:.0%} ({m.method})"
            for m in result.matches[:3]
        )

        # Build dimension picker buttons (2 per row)
        dim_names = list(DIMENSION_TOPICS.keys())
        buttons = [
            InlineKeyboardButton(
                dim_name,
                callback_data=_cb({"a": "bnc", "m": msg_id, "d": i}),
            )
            for i, dim_name in enumerate(dim_names)
        ]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        keyboard = InlineKeyboardMarkup(rows)

        preview = text[:300] + ("..." if len(text) > 300 else "")
        bouncer_text = (
            "<b>Unsure where this goes</b>\n\n"
            f"<blockquote>{preview}</blockquote>\n\n"
            f"<b>My best guesses:</b>\n{scores_text}\n\n"
            f"<i>Which dimension is correct?</i>"
        )

        # Store in pending_captures
        all_scores = json.dumps([
            {"dimension": m.dimension, "confidence": m.confidence, "method": m.method}
            for m in result.matches
        ])
        await execute(
            "INSERT INTO pending_captures "
            "(message_text, message_ts, chat_id, user_id, all_scores_json, "
            "primary_dimension, primary_confidence, method, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (text, str(msg_id), str(update.effective_chat.id),
             str(update.effective_user.id), all_scores,
             dimensions[0] if dimensions else None, confidence, method),
        )

        # Send DM to owner with picker
        dm_msg = await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=bouncer_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        # Update DB with DM message info
        await execute(
            "UPDATE pending_captures SET bouncer_dm_ts = ?, bouncer_dm_channel = ? "
            "WHERE message_ts = ?",
            (str(dm_msg.message_id), str(update.effective_user.id), str(msg_id)),
        )

        logger.info(
            "Low-confidence bouncer: msg_id=%s, confidence=%.2f, dims=%s",
            msg_id, confidence, dimensions,
        )

    except Exception:
        logger.exception("Failed to handle low-confidence capture")


async def handle_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages — classify and route inbox captures."""
    if not update.message or not update.message.text:
        return

    # Owner check
    if OWNER_TELEGRAM_ID and (
        not update.effective_user or update.effective_user.id != OWNER_TELEGRAM_ID
    ):
        return

    # Only process messages in the inbox topic (if topics are configured)
    inbox_topic_id = TOPICS.get("brain-inbox")
    if inbox_topic_id:
        if update.message.message_thread_id != inbox_topic_id:
            return
    elif GROUP_CHAT_ID and update.effective_chat.id == GROUP_CHAT_ID:
        # In group chat without topics configured, skip (avoid capturing everything)
        return

    text = update.message.text
    msg_id = update.message.message_id

    # Classify via hybrid pipeline (sync — run in executor)
    result = await run_in_executor(_classifier.classify, text)

    # Noise filter
    if result.is_noise:
        logger.info("Noise filtered: %r", text[:80])
        await update.message.reply_text(
            "Hey! Drop a thought, idea, or task here and I'll route it to the right place."
        )
        return

    # Confidence bouncer
    top_confidence = result.matches[0].confidence if result.matches else 0.0
    if result.matches and top_confidence < config.CONFIDENCE_THRESHOLD:
        await _handle_low_confidence(update, context, result)
        return

    try:
        dimensions = [m.dimension for m in result.matches]
        confidence = result.matches[0].confidence if result.matches else 0.0
        method = result.matches[0].method if result.matches else "none"

        logger.info(
            "Classified %r: dims=%s confidence=%.2f method=%s (%.0fms)",
            text[:60], dimensions, confidence, method, result.execution_time_ms,
        )

        # --- Vault writes ---
        today = datetime.now().strftime("%Y-%m-%d")

        capture_line = format_capture_line(
            text, dimensions=dimensions, is_action=result.is_actionable,
        )
        await run_in_executor(append_to_daily_note, today, capture_line, section="## Log")

        await run_in_executor(
            create_inbox_entry, text, source="telegram",
            dimensions=dimensions, confidence=confidence, method=method,
        )

        # Action item dual-write
        if result.is_actionable:
            primary_dim = dimensions[0] if dimensions else None
            await insert_action_item(
                description=text,
                source="telegram-inbox",
                icor_element=primary_dim,
            )

        # Detect URLs for article ingestion
        try:
            from core.article_fetcher import extract_urls
            urls = extract_urls(text)
            if urls:
                for url in urls[:2]:
                    context.application.create_task(
                        _ingest_article(context.bot, update.effective_chat.id,
                                        TOPICS.get("brain-inbox"), url, dimensions)
                    )
        except ImportError:
            pass
        except Exception:
            logger.debug("URL detection failed")

        # Log classification to DB
        await _log_classification(text, msg_id, result)

        # Log to captures_log
        if dimensions:
            try:
                await execute(
                    "INSERT INTO captures_log "
                    "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (text, json.dumps(dimensions), confidence, method,
                     1 if result.is_actionable else 0, "brain-inbox"),
                )
            except Exception:
                logger.exception("Failed to log capture to captures_log")

        # Reply with confirmation + feedback buttons
        confirm_text, _ = format_capture_confirmation(text, dimensions, [])

        feedback_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "\u2705 Correct",
                callback_data=_cb({"a": "fb_ok", "m": msg_id}),
            ),
            InlineKeyboardButton(
                "\u274c Wrong",
                callback_data=_cb({"a": "fb_no", "m": msg_id}),
            ),
        ]])

        await update.message.reply_text(
            confirm_text,
            parse_mode="HTML",
            reply_markup=feedback_keyboard,
        )

    except Exception:
        logger.exception("Error processing capture")
        try:
            error_text, _ = format_error("Failed to process capture. Check bot logs.")
            await update.message.reply_text(error_text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send error message")


async def process_bouncer_resolution(text: str, msg_id: int, dimension: str, chat_id: int | None):
    """Complete routing for a bounced capture after user clarification."""
    try:
        # Log to captures_log
        await execute(
            "INSERT INTO captures_log "
            "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
            "VALUES (?, ?, 1.0, 'user_clarified', 0, ?)",
            (text, json.dumps([dimension]), "brain-inbox"),
        )

        # Update classification record
        await execute(
            "UPDATE classifications SET user_correction = ? WHERE message_ts = ?",
            (dimension, str(msg_id)),
        )

    except Exception:
        logger.exception("Failed to finalize bounced capture")


async def _ingest_article(bot, chat_id: int, topic_id: int | None, url: str, dimensions: list[str]):
    """Fetch article, summarize, save to vault."""
    try:
        from core.article_fetcher import fetch_article
        from core.vault_ops import create_web_clip
        import html as html_mod

        article = await run_in_executor(fetch_article, url)
        if not article:
            return

        summary = article.content[:500] + "..." if len(article.content) > 500 else article.content
        await run_in_executor(
            create_web_clip,
            url=url, title=article.title, summary=summary,
            icor_elements=dimensions, content_preview=article.content[:2000],
        )

        safe_title = html_mod.escape(article.title)
        safe_summary = html_mod.escape(summary[:200])
        text = f"\U0001f4f0 <b>Article saved:</b> {safe_title}\n{safe_summary}..."
        kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if topic_id:
            kwargs["message_thread_id"] = topic_id
        await bot.send_message(**kwargs)

        logger.info("Ingested article: %s", url)

    except Exception:
        logger.exception("Article ingestion failed for %s", url)


def register(application: Application):
    """Register the inbox capture handler."""

    # Ensure dimension wikilink targets exist in vault
    try:
        ensure_dimension_pages()
    except Exception:
        logger.exception("Failed to ensure dimension pages")

    # Register text message handler (higher priority than app.py catch-all)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_capture),
        group=1,
    )

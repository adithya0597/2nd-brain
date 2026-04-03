"""Inbox message capture and routing handler for Telegram.

Listens for text messages (in the inbox topic if configured), classifies
the ICOR dimension, saves to vault + SQLite, and replies with confirmation
and feedback buttons.
"""
import json
import logging
import time as _time
from datetime import date, datetime, timedelta

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
from core.vault_ops import (
    append_to_daily_note,
    create_inbox_entry,
    ensure_dimension_pages,
    format_capture_line,
)

logger = logging.getLogger(__name__)

# Module-level classifier instance
_classifier = MessageClassifier()

# Pending extraction results awaiting user confirmation (keyed by extraction_id).
# Each value is a (extraction, timestamp) tuple. Entries older than 15 min are
# pruned on each new insertion to prevent unbounded growth.
_EXTRACTION_TTL_SECONDS = 900  # 15 minutes
_pending_extractions: dict[str, tuple[object, float]] = {}


_INTENT_CONFIRM_LABELS = {
    "task": "\u2705 Create Task",
    "idea": "\U0001f4a1 Save Idea",
    "reflection": "\U0001fa9e Add to Journal",
    "update": "\U0001f4dd Save Update",
    "link": "\U0001f517 Save Link",
    "question": "\u2753 Save Question",
}


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

        # Action item dual-write — SKIP if extraction will handle it
        # (the extraction confirm handler inserts a structured action item instead)
        _skip_raw_action_insert = False

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

        # --- Single response: extraction confirm OR dimension confirm ---
        # Run extraction BEFORE sending any reply so the user gets one message,
        # not two.
        # Separate extraction gate from action-item gate:
        #   is_actionable: drives action checkbox + raw action item (narrow regex)
        #   should_extract: drives LLM extraction (broader, includes temporal patterns)
        sent_extraction = False
        extraction = None
        should_extract = _classifier.check_should_extract(text)
        if should_extract:
            try:
                from core.intent_extractor import extract_intent, _load_registry

                registry_data = _load_registry()
                extraction = await extract_intent(text, registry_data)
                logger.info(
                    "Extraction: intent=%s project=%s due=%s conf=%.2f",
                    extraction.intent,
                    extraction.project,
                    extraction.due_date,
                    extraction.confidence,
                )

                # Show extraction UI for ALL intents when confident enough.
                # 0.3 threshold: at 2-5 captures/day, false positives cost one Skip tap.
                if extraction and extraction.confidence > 0.3:
                    from core.formatter import format_extraction_confirmation

                    confirm_msg = format_extraction_confirmation(extraction)
                    extraction_id = str(msg_id)
                    # Store with timestamp for TTL
                    _pending_extractions[extraction_id] = (extraction, _time.time())
                    # Prune expired entries
                    cutoff = _time.time() - _EXTRACTION_TTL_SECONDS
                    for k in [k for k, v in _pending_extractions.items() if v[1] < cutoff]:
                        del _pending_extractions[k]

                    confirm_label = _INTENT_CONFIRM_LABELS.get(
                        extraction.intent, "\U0001f4e5 Save"
                    )
                    confirm_keyboard = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    confirm_label,
                                    callback_data=_cb(
                                        {"a": "ext_ok", "e": extraction_id}
                                    ),
                                ),
                                InlineKeyboardButton(
                                    "\u270f\ufe0f Edit",
                                    callback_data=_cb(
                                        {"a": "ext_edit", "e": extraction_id}
                                    ),
                                ),
                                InlineKeyboardButton(
                                    "\u274c Skip",
                                    callback_data=_cb(
                                        {"a": "ext_skip", "e": extraction_id}
                                    ),
                                ),
                            ]
                        ]
                    )

                    await update.message.reply_text(
                        confirm_msg,
                        parse_mode="HTML",
                        reply_markup=confirm_keyboard,
                    )
                    sent_extraction = True
                    _skip_raw_action_insert = True
            except Exception:
                logger.exception("Intent extraction failed for capture")

        # Insert raw action item ONLY if extraction didn't take over
        if result.is_actionable and not _skip_raw_action_insert:
            primary_dim = dimensions[0] if dimensions else None
            await insert_action_item(
                description=text,
                source="telegram-inbox",
                icor_element=primary_dim,
            )

        # Fall back to dimension classification confirm if extraction didn't
        # produce a task confirmation message.
        if not sent_extraction:
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


# ---------------------------------------------------------------------------
# Extraction confirmation callback handlers
# ---------------------------------------------------------------------------


async def _create_notion_task_immediate(extraction, action_id: int):
    """Create a Notion task immediately from extraction result."""
    try:
        import os

        from core.notion_client import NotionClientWrapper
        from core.notion_mappers import (
            build_date_property,
            build_relation_property,
            build_status_property,
            build_title_property,
        )

        notion_token = os.environ.get("NOTION_TOKEN")
        if not notion_token:
            logger.warning("NOTION_TOKEN not set, skipping immediate Notion push")
            return

        props = {
            "Name": build_title_property(extraction.title),
            "Status": build_status_property("To Do"),
        }

        if extraction.due_date:
            props["Due"] = build_date_property(extraction.due_date)

        if extraction.priority:
            priority_map = {"high": "High", "medium": "Medium", "low": "Low"}
            mapped = priority_map.get(extraction.priority, "Medium")
            props["Priority"] = build_status_property(mapped)

        # Link to project if matched
        if extraction.project:
            from core.intent_extractor import _load_registry

            registry = _load_registry()
            project_data = registry.get("projects", {}).get(extraction.project, {})
            notion_id = project_data.get("notion_page_id")
            if notion_id:
                props["Project"] = build_relation_property([notion_id])

        # Link to people if matched
        if extraction.people:
            from core.intent_extractor import _load_registry

            registry = _load_registry()
            people_ids = []
            for person_name in extraction.people:
                person_data = registry.get("people", {}).get(person_name, {})
                pid = person_data.get("notion_page_id")
                if pid:
                    people_ids.append(pid)
            if people_ids:
                props["People"] = build_relation_property(people_ids)

        tasks_db_id = config.NOTION_COLLECTIONS["tasks"].replace("collection://", "")

        client = NotionClientWrapper(notion_token)
        try:
            page = await client.create_page(
                parent={"data_source_id": tasks_db_id},
                properties=props,
            )
        finally:
            await client.close()

        # Update action item with Notion page ID
        from core.db_ops import update_action_external

        await update_action_external(action_id, page["id"])

        logger.info(
            "Created Notion task immediately: %s (page %s)",
            extraction.title,
            page["id"],
        )

    except Exception as e:
        logger.error("Immediate Notion push failed (will sync later): %s", e)


async def handle_extraction_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle extraction confirmation -- create structured task."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    extraction_id = data.get("e")
    extraction, _ts = _pending_extractions.pop(extraction_id, (None, 0))

    if not extraction:
        await query.edit_message_text("Extraction expired. Please recapture.")
        return

    try:
        from core.formatter import _esc

        if extraction.intent == "task":
            # TASK: create action item + Notion push + reminder
            action_id = await insert_action_item(
                description=extraction.title,
                source="telegram-extraction",
                icor_element=None,
                due_date=extraction.due_date,
            )

            # Create Notion task immediately
            await _create_notion_task_immediate(extraction, action_id)

            # Schedule reminder if due soon (today or tomorrow)
            if extraction.due_date:
                try:
                    due = date.fromisoformat(extraction.due_date)
                    today = date.today()
                    if today <= due <= today + timedelta(days=1):
                        from core.reminder_manager import schedule_reminder

                        await schedule_reminder(
                            context.job_queue, action_id, extraction.title, extraction.due_date
                        )
                except Exception:
                    logger.debug("Reminder scheduling failed", exc_info=True)

            result_parts = [f"\u2705 <b>Task created:</b> {_esc(extraction.title)}"]
            if extraction.due_date:
                result_parts.append(f"\U0001f4c5 Due: {extraction.due_date}")
        else:
            # NON-TASK: log feedback only. Data already in daily note + inbox.
            intent_emoji = {
                "idea": "\U0001f4a1", "reflection": "\U0001fa9e",
                "update": "\U0001f4dd", "link": "\U0001f517",
                "question": "\u2753",
            }.get(extraction.intent, "\U0001f4e5")
            result_parts = [
                f"{intent_emoji} <b>{extraction.intent.title()} noted:</b> {_esc(extraction.title)}"
            ]

        # Common fields for all intents
        if extraction.project:
            result_parts.append(f"\U0001f4c1 Project: {_esc(extraction.project)}")
        if extraction.people:
            result_parts.append(
                f"\U0001f464 {', '.join(_esc(p) for p in extraction.people)}"
            )

        # Log feedback for all intents
        await execute(
            "INSERT OR IGNORE INTO extraction_feedback "
            "(capture_id, field_name, proposed_value, confirmed_value, was_correct) "
            "VALUES (?, 'all', ?, ?, 1)",
            (int(extraction_id), extraction.title, extraction.title),
        )

        await query.edit_message_text("\n".join(result_parts), parse_mode="HTML")

    except Exception as e:
        logger.error("Failed to process extraction confirm: %s", e)
        await query.edit_message_text(f"\u274c Failed to process: {e}")


async def handle_extraction_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skipping an extraction."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    extraction_id = data.get("e")
    _pending_extractions.pop(extraction_id, (None, 0))

    await query.edit_message_text("\u23ed\ufe0f Skipped \u2014 capture saved as-is.")


async def handle_extraction_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle extraction edit -- show field correction options."""
    query = update.callback_query
    await query.answer()

    data = json.loads(query.data)
    extraction_id = data.get("e")
    entry = _pending_extractions.get(extraction_id)

    if not entry:
        await query.edit_message_text("Extraction expired. Please recapture.")
        return

    extraction, _ts = entry

    # Show individual field buttons so user can see what was extracted
    buttons = []
    if extraction.title:
        buttons.append([InlineKeyboardButton(
            f"\U0001f4cc Title: {extraction.title[:30]}",
            callback_data=_cb({"a": "ext_field", "e": extraction_id, "f": "title"}),
        )])
    if extraction.due_date:
        buttons.append([InlineKeyboardButton(
            f"\U0001f4c5 Due: {extraction.due_date}",
            callback_data=_cb({"a": "ext_field", "e": extraction_id, "f": "due"}),
        )])
    if extraction.project:
        buttons.append([InlineKeyboardButton(
            f"\U0001f4c1 Project: {extraction.project[:30]}",
            callback_data=_cb({"a": "ext_field", "e": extraction_id, "f": "project"}),
        )])
    # Always show confirm and Skip at bottom
    confirm_label = _INTENT_CONFIRM_LABELS.get(extraction.intent, "\U0001f4e5 Save")
    buttons.append([
        InlineKeyboardButton(
            confirm_label,
            callback_data=_cb({"a": "ext_ok", "e": extraction_id}),
        ),
        InlineKeyboardButton(
            "\u274c Skip",
            callback_data=_cb({"a": "ext_skip", "e": extraction_id}),
        ),
    ])

    from core.formatter import format_extraction_confirmation

    text = format_extraction_confirmation(extraction)
    text += "\n\n<i>Tap a field to edit (reply with new value), or Create/Skip:</i>"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def register(application: Application):
    """Register the inbox capture handler and extraction callbacks."""
    from telegram.ext import CallbackQueryHandler

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

    # Extraction confirmation callbacks
    application.add_handler(
        CallbackQueryHandler(handle_extraction_confirm, pattern=r'\{"a":"ext_ok"')
    )
    application.add_handler(
        CallbackQueryHandler(handle_extraction_edit, pattern=r'\{"a":"ext_edit"')
    )
    application.add_handler(
        CallbackQueryHandler(handle_extraction_skip, pattern=r'\{"a":"ext_skip"')
    )

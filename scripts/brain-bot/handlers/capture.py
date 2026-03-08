"""Inbox message routing handler.

Listens for messages in #brain-inbox, classifies the ICOR dimension,
routes to the appropriate channel, and saves to daily note + vault inbox.
"""
import json
import logging
from datetime import datetime

from slack_bolt import App

import config
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


def _handle_low_confidence(client, event, channel_ids: dict, result):
    """Route low-confidence captures to user DM for manual disambiguation."""
    text = event.get("text", "")
    user = event.get("user", "")
    channel = event.get("channel", "")
    ts = event.get("ts", "")

    if not user or not text:
        return

    try:
        # Still save to daily note and inbox (unrouted)
        today = datetime.now().strftime("%Y-%m-%d")
        capture_line = format_capture_line(text, dimensions=[], is_action=result.is_actionable)
        append_to_daily_note(today, capture_line, section="## Log")
        create_inbox_entry(
            text, source="slack", dimensions=[],
            confidence=result.matches[0].confidence,
            method="pending_clarification",
        )

        # Log classification
        _log_classification(text, ts, result)

        dimensions = [m.dimension for m in result.matches]
        confidence = result.matches[0].confidence
        method = result.matches[0].method

        # Build scores text
        scores_text = "\n".join(
            f"  {m.dimension} -- {m.confidence:.0%} ({m.method})"
            for m in result.matches[:3]
        )

        # Build dimension picker options
        options = [
            {
                "text": {"type": "plain_text", "text": dim_name},
                "value": json.dumps({
                    "ts": ts, "dimension": dim_name,
                    "text": text[:500], "channel": channel,
                }),
            }
            for dim_name in DIMENSION_CHANNELS.keys()
        ]

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Unsure where this goes", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "I'm not confident about this capture:\n\n"
                        f"> {text[:300]}{'...' if len(text) > 300 else ''}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*My best guesses:*\n{scores_text}\n\n*Which dimension is correct?*",
                },
            },
            {
                "type": "actions",
                "block_id": f"bouncer_{ts}",
                "elements": [
                    {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "Select dimension"},
                        "action_id": "bouncer_select_dimension",
                        "options": options[:25],  # Slack max
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"_Confidence: {confidence:.0%} | Auto-filing in "
                            f"{config.BOUNCER_TIMEOUT_MINUTES} min to "
                            f"{dimensions[0] if dimensions else 'Unknown'}_"
                        ),
                    }
                ],
            },
        ]

        # Store in pending_captures BEFORE sending DM (so capture is never lost)
        all_scores = json.dumps([
            {"dimension": m.dimension, "confidence": m.confidence, "method": m.method}
            for m in result.matches
        ])
        run_async(execute(
            "INSERT INTO pending_captures "
            "(message_text, message_ts, channel_id, slack_user_id, all_scores_json, "
            "primary_dimension, primary_confidence, method, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (text, ts, channel, user, all_scores,
             dimensions[0] if dimensions else None, confidence, method),
        ))

        # Send DM (if this fails, capture is still safe in DB for timeout resolution)
        dm = client.conversations_open(users=[user])
        dm_channel = dm["channel"]["id"]
        dm_result = client.chat_postMessage(
            channel=dm_channel,
            text=f"Need help routing: {text[:50]}...",
            blocks=blocks,
        )

        # Update the DB row with DM details for timeout message updates
        run_async(execute(
            "UPDATE pending_captures SET bouncer_dm_ts = ?, bouncer_dm_channel = ? "
            "WHERE message_ts = ?",
            (dm_result["ts"], dm_channel, ts),
        ))

        logger.info(
            "Low-confidence bouncer: ts=%s, confidence=%.2f, dims=%s",
            ts, confidence, dimensions,
        )

    except Exception:
        logger.exception("Failed to handle low-confidence capture, falling back to normal routing")


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

    # Confidence bouncer: if top match < threshold, ask user to clarify
    top_confidence = result.matches[0].confidence if result.matches else 0.0
    if result.matches and top_confidence < config.CONFIDENCE_THRESHOLD:
        _handle_low_confidence(client, event, channel_ids, result)
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

        # Detect and process URLs for article ingestion
        try:
            from core.article_fetcher import extract_urls
            urls = extract_urls(text)
            if urls:
                for url in urls[:2]:  # Max 2 URLs per capture
                    executor.submit(_ingest_article, client, channel, ts, url, dimensions)
        except ImportError:
            pass
        except Exception:
            logger.debug("URL detection failed")

        # Log classification to DB
        _log_classification(text, ts, result)

        # --- Log to captures_log (replaces dimension channel routing) ---
        if dimensions:
            import json as _json
            try:
                run_async(execute(
                    "INSERT INTO captures_log "
                    "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (text, _json.dumps(dimensions), confidence, method,
                     1 if result.is_actionable else 0, "brain-inbox"),
                ))
            except Exception:
                logger.exception("Failed to log capture to captures_log")

        # Reply in thread in #brain-inbox
        blocks = format_capture_confirmation(text, dimensions, [])
        # Append feedback buttons
        blocks.extend(_build_feedback_buttons(ts, dimensions))

        summary_text = (
            f"Captured: {' + '.join(dimensions)}"
            if dimensions
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


def _process_bouncer_resolution(client, text: str, ts: str, dimension: str, inbox_channel: str):
    """Complete routing for a bounced capture after user clarification."""
    try:
        import json as _json

        # Log to captures_log (replaces dimension channel routing)
        run_async(execute(
            "INSERT INTO captures_log "
            "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
            "VALUES (?, ?, 1.0, 'user_clarified', 0, ?)",
            (text, _json.dumps([dimension]), "brain-inbox"),
        ))

        # Reply in inbox thread
        if inbox_channel:
            client.chat_postMessage(
                channel=inbox_channel,
                thread_ts=ts,
                text=f"Filed to {dimension} (user-clarified)",
            )

        # Update classification record
        run_async(execute(
            "UPDATE classifications SET user_correction = ? WHERE message_ts = ?",
            (dimension, ts),
        ))

    except Exception:
        logger.exception("Failed to finalize bounced capture")


def _ingest_article(client, channel: str, ts: str, url: str, dimensions: list[str]):
    """Background: fetch article, summarize, save to vault."""
    try:
        from core.article_fetcher import fetch_article
        from core.vault_ops import create_web_clip

        article = fetch_article(url)
        if not article:
            return

        # Create vault file with article content
        summary = article.content[:500] + "..." if len(article.content) > 500 else article.content
        path = create_web_clip(
            url=url,
            title=article.title,
            summary=summary,
            icor_elements=dimensions,
            content_preview=article.content[:2000],
        )

        # Reply in thread with confirmation
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"Saved article: {article.title}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":newspaper: *Article saved:* {article.title}\n{summary[:200]}...",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Saved to vault/Resources/ | {len(article.content)} chars extracted"},
                    ],
                },
            ],
        )

        logger.info("Ingested article: %s -> %s", url, path)

    except Exception:
        logger.exception("Article ingestion failed for %s", url)


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

"""Scheduled automations for the Second Brain Telegram bot.

Uses PTB v21's JobQueue for cron-like job scheduling.
Jobs are registered at startup via register_jobs(job_queue).
"""
import html
import json
import logging
import sqlite3
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram.ext import CallbackContext

from config import (
    DB_PATH,
    DIMENSION_KEYWORDS,
    GROUP_CHAT_ID,
    NOTION_COLLECTIONS,
    NOTION_REGISTRY_PATH,
    NOTION_TOKEN,
    TOPICS,
    VAULT_PATH,
    load_dynamic_keywords,
)
from core.ai_client import get_ai_client, get_ai_model
from core.context_loader import (
    build_claude_messages,
    gather_command_context,
    load_command_prompt,
    load_system_context,
)
from core.db_ops import (
    compute_attention_scores,
    execute,
    get_attention_scores,
    get_neglected_elements,
    get_pending_actions,
    get_recent_journal,
    query,
)
from core.formatter import (
    format_dashboard,
    format_error,
    format_sync_report,
)
from core.message_utils import send_long_message
from core.notion_client import NotionClientWrapper
from core.notion_sync import NotionSync

logger = logging.getLogger(__name__)

CST = ZoneInfo("America/Chicago")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_job_run(job_name: str):
    """Record that a scheduled job ran successfully."""
    try:
        from core.db_connection import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scheduler_state (job_name, last_run_at, updated_at) "
                "VALUES (?, datetime('now'), datetime('now'))",
                (job_name,),
            )
            conn.commit()
    except Exception:
        logger.warning("Failed to record job run: %s", job_name)


async def _notify_job_failure(bot, job_name: str, error: Exception):
    """Send job failure notification to brain-daily topic (user-facing jobs only)."""
    try:
        error_text = str(error)[:200]
        text = f"<b>Job Failed: {job_name}</b>\n<code>{error_text}</code>"
        await _send_to_topic(bot, "brain-daily", text)
    except Exception:
        logger.debug("Failed to send job failure notification", exc_info=True)


def _should_run_biweekly(job_name: str) -> bool:
    """Check if a bi-weekly job should run (2 weeks since last run)."""
    try:
        from core.db_connection import get_connection
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT last_run_at FROM scheduler_state WHERE job_name = ?",
                (job_name,),
            )
            row = cursor.fetchone()
        if not row or not row[0]:
            return True
        last_run = datetime.fromisoformat(row[0])
        return datetime.now() - last_run >= timedelta(days=13)
    except Exception:
        return True


async def _call_claude(brain_command: str, user_input: str = "") -> str:
    """Gather context, call Claude, return text response."""
    context = await gather_command_context(brain_command)
    system_ctx = load_system_context()
    prompt = load_command_prompt(brain_command)
    messages = build_claude_messages(brain_command, user_input, context)

    ai = get_ai_client()
    if ai is None:
        raise RuntimeError("AI client not initialized — check GEMINI_API_KEY or ANTHROPIC_API_KEY in .env")
    model = get_ai_model()
    response = await ai.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system_ctx,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=messages,
    )

    try:
        from core.token_logger import log_token_usage
        log_token_usage(response, caller=f"scheduled_{brain_command}", model=model)
    except Exception:
        pass

    return response.content[0].text


async def _send_to_topic(bot, topic_name: str, text: str, keyboard=None):
    """Send a message to a forum topic, splitting if needed."""
    topic_id = TOPICS.get(topic_name)
    if not topic_id:
        logger.warning("Topic %s not configured, skipping send", topic_name)
        return None
    return await send_long_message(
        bot,
        chat_id=GROUP_CHAT_ID,
        text=text,
        reply_markup=keyboard,
        topic_id=topic_id,
    )


# ---------------------------------------------------------------------------
# Job Functions
# ---------------------------------------------------------------------------

async def job_morning_briefing(context: CallbackContext):
    """Daily 7am: Full AI-powered morning briefing."""
    try:
        logger.info("Running morning briefing job")
        result = await _call_claude("today")
        await _send_to_topic(context.bot, "brain-daily", result)
        _record_job_run("morning_briefing")
    except Exception as e:
        logger.exception("Morning briefing job failed")
        await _notify_job_failure(context.bot, "morning_briefing", e)


async def job_evening_prompt(context: CallbackContext):
    """Daily 9pm: Structured evening review prompt (template, no full AI)."""
    try:
        logger.info("Running evening prompt job")
        pending = await get_pending_actions()
        recent = await get_recent_journal(days=1)

        journal_status = "Yes" if recent else "Not yet"
        pending_count = len(pending)

        text = (
            "<b>Evening Review Time</b>\n\n"
            f"<b>Journal today:</b> {journal_status}\n"
            f"<b>Pending actions:</b> {pending_count}\n\n"
            "<b>Reflection prompts:</b>\n"
            "1. What went well today?\n"
            "2. What challenged you?\n"
            "3. What will you carry forward to tomorrow?\n"
            "4. Any new ideas or insights?\n\n"
            "<i>Run /close when you're ready for the full evening review.</i>"
        )

        # Fading memories section (Mon/Wed/Fri only, skip if no journal)
        fading_kb = None
        weekday = datetime.now().weekday()
        show_fading = weekday in (0, 2, 4) and recent  # recent = journal entries exist

        if show_fading:
            try:
                fading = await query("""
                    SELECT n.title, n.indexed_at, n.file_path,
                           COUNT(e.id) AS edge_count,
                           CAST(julianday('now') - julianday(n.indexed_at) AS INTEGER) AS days_old
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
                    GROUP BY n.id HAVING edge_count >= 3
                    ORDER BY days_old DESC LIMIT 3
                """)
                if fading:
                    from core.formatter import format_fading_memories
                    fading_section, fading_kb = format_fading_memories(fading)
                    text += fading_section
            except Exception:
                logger.debug("Fading memories query failed", exc_info=True)

        await _send_to_topic(context.bot, "brain-daily", text, fading_kb)
        _record_job_run("evening_prompt")
    except Exception as e:
        logger.exception("Evening prompt job failed")
        await _notify_job_failure(context.bot, "evening_prompt", e)


async def job_dashboard_refresh(context: CallbackContext):
    """Twice daily: Recompute attention scores + dashboard refresh."""
    try:
        logger.info("Running dashboard refresh job")
        scored = await compute_attention_scores(days=30)
        logger.info("Attention scores computed for %d elements", scored)
        pending = await get_pending_actions()
        attention = await get_attention_scores()
        neglected = await get_neglected_elements()

        # Build ICOR data grouped by dimension
        icor_data: dict[str, list] = {}
        for score in attention:
            dim = score.get("dimension", "Unknown")
            if dim not in icor_data:
                icor_data[dim] = []
            icor_data[dim].append(score)

        text, keyboard = format_dashboard(icor_data, [], pending)

        # Add neglected elements
        if neglected:
            neglected_text = "\n".join(
                f"\u2022 <b>{n['name']}</b> ({n.get('dimension', 'N/A')}) \u2014 "
                f"{int(n.get('days_since') or 0)} days silent"
                for n in neglected[:5]
            )
            text += f"\n\n<b>Neglected Elements:</b>\n{neglected_text}"

        # Add graph density metric
        try:
            from core.graph_maintenance import compute_graph_density
            density_info = compute_graph_density()
            density_pct = density_info.get("density", 0)
            node_count = density_info.get("node_count", 0)
            edge_count = density_info.get("edge_count", 0)
            text += (
                f"\n\n<b>Graph:</b> {node_count} nodes, {edge_count} edges "
                f"(density {density_pct:.1%})"
            )
        except Exception:
            logger.debug("Graph density unavailable for dashboard", exc_info=True)

        await _send_to_topic(context.bot, "brain-dashboard", text, keyboard)

        # Run alert checks during dashboard refresh
        try:
            from core.alerts import run_all_checks
            alert_result = run_all_checks()
            if alert_result["total_new"] > 0:
                logger.info("Alert checks: %d new alerts", alert_result["total_new"])
        except Exception:
            logger.warning("Alert checks failed during dashboard refresh", exc_info=True)

        _record_job_run("dashboard_refresh")

        # Update pinned dashboard if available
        try:
            from handlers.dashboard import update_pinned_dashboard
            await update_pinned_dashboard(context.bot)
        except Exception:
            logger.debug("Pinned dashboard update skipped", exc_info=True)

    except Exception:
        logger.exception("Dashboard refresh job failed")


async def job_notion_sync(context: CallbackContext):
    """Daily 10pm: Python-native Notion sync (post summary on error)."""
    if not NOTION_TOKEN:
        logger.warning("NOTION_TOKEN not set - skipping Notion sync")
        return
    try:
        logger.info("Running Notion sync job (Python-native)")

        notion = NotionClientWrapper(token=NOTION_TOKEN)
        try:
            syncer = NotionSync(
                client=notion,
                registry_path=NOTION_REGISTRY_PATH,
                db_path=DB_PATH,
                vault_path=VAULT_PATH,
                collection_ids=NOTION_COLLECTIONS,
                ai_client=get_ai_client(),
                ai_model=get_ai_model(),
            )
            result = await syncer.run_full_sync()
        finally:
            await notion.close()

        logger.info("Notion sync completed: %s", result.summary())

        # Post summary if there were errors
        if result.errors:
            text, keyboard = format_sync_report(result)
            await _send_to_topic(context.bot, "brain-daily", text, keyboard)

        _record_job_run("notion_sync")
    except Exception:
        logger.exception("Notion sync job failed")
        text, _ = format_error("Scheduled Notion sync failed. Check bot logs.")
        await _send_to_topic(context.bot, "brain-daily", text)


async def job_drift_report(context: CallbackContext):
    """Weekly Sunday 6pm: Drift analysis."""
    try:
        logger.info("Running weekly drift report job")
        result = await _call_claude("drift")
        await _send_to_topic(context.bot, "brain-insights", result)
        _record_job_run("drift_report")
    except Exception as e:
        logger.exception("Drift report job failed")
        await _notify_job_failure(context.bot, "drift_report", e)


async def job_emerge_biweekly(context: CallbackContext):
    """Bi-weekly Wednesday 2pm: Pattern synthesis."""
    if not _should_run_biweekly("emerge_biweekly"):
        logger.info("Skipping emerge job (less than 2 weeks since last run)")
        return
    try:
        logger.info("Running bi-weekly emerge job")
        result = await _call_claude("emerge")
        await _send_to_topic(context.bot, "brain-insights", result)
        _record_job_run("emerge_biweekly")
    except Exception:
        logger.exception("Emerge job failed")


async def job_weekly_project_summary(context: CallbackContext):
    """Weekly Monday 9am: AI-powered project summary."""
    try:
        logger.info("Running weekly project summary job")
        result = await _call_claude("projects")
        await _send_to_topic(context.bot, "brain-daily", result)
        _record_job_run("weekly_project_summary")
    except Exception:
        logger.exception("Weekly project summary job failed")


async def job_monthly_resource_digest(context: CallbackContext):
    """Monthly 1st at 10am: AI-powered resource digest."""
    today = datetime.now()
    if today.day != 1:
        return  # Only run on the 1st of the month
    try:
        logger.info("Running monthly resource digest job")
        result = await _call_claude("resources")
        await _send_to_topic(context.bot, "brain-daily", result)
        _record_job_run("monthly_resource_digest")
    except Exception:
        logger.exception("Monthly resource digest job failed")


async def job_vault_reindex(context: CallbackContext):
    """Daily 5am: Re-index vault files and journal entries."""
    try:
        from core.async_utils import run_in_executor
        from core.vault_indexer import run_full_index as index_vault
        from core.journal_indexer import run_full_index as index_journal

        vault_count = await run_in_executor(index_vault)
        journal_count = await run_in_executor(index_journal)
        logger.info("Vault reindex: %d files, %d journal entries", vault_count, journal_count)

        # Populate FTS5 index after vault reindex
        try:
            from core.fts_index import populate_fts
            fts_count = await run_in_executor(populate_fts, db_path=str(DB_PATH), vault_path=str(VAULT_PATH))
            logger.info("FTS5 index populated: %d files", fts_count)
        except Exception as e:
            logger.warning("FTS5 population failed: %s", e)

        # Rebuild ICOR affinity edges + community detection
        try:
            from core.icor_affinity import rebuild_all_icor_edges
            from core.community import update_community_ids
            affinity_count = await run_in_executor(rebuild_all_icor_edges)
            community_count = await run_in_executor(update_community_ids)
            logger.info("Graph: %d affinity edges, %d community assignments",
                        affinity_count, community_count)
        except Exception as e:
            logger.warning("ICOR affinity/community rebuild failed: %s", e)

        # Rebuild tag-shared edges (co-tag overlap between documents)
        try:
            from core.graph_ops import rebuild_tag_shared_edges
            tag_count = await run_in_executor(rebuild_tag_shared_edges)
            logger.info("Tag shared edges rebuilt: %d", tag_count)
        except Exception as e:
            logger.warning("Tag shared edge rebuild failed: %s", e)

        # Rebuild semantic similarity edges (embedding-based document similarity)
        try:
            from core.graph_ops import rebuild_semantic_similarity_edges
            sim_count = await run_in_executor(rebuild_semantic_similarity_edges)
            logger.info("Semantic similarity edges rebuilt: %d", sim_count)
        except Exception as e:
            logger.warning("Semantic similarity edge rebuild failed: %s", e)

        _record_job_run("vault_reindex")
    except Exception:
        logger.exception("Vault reindex job failed")


async def job_keyword_expansion(context: CallbackContext):
    """Weekly Sunday 2am: Expand keywords from recent corrections using Claude."""
    if not get_ai_client():
        logger.info("No Anthropic client configured - skipping keyword expansion")
        return

    try:
        logger.info("Running weekly keyword expansion job")

        # Get recent corrections
        corrections = await query(
            "SELECT message_text, primary_dimension, user_correction "
            "FROM classifications "
            "WHERE user_correction IS NOT NULL "
            "AND corrected_at >= datetime('now', '-7 days') "
            "ORDER BY corrected_at DESC LIMIT 50",
        )

        if not corrections:
            logger.info("No recent corrections - skipping keyword expansion")
            return

        # Format corrections for Claude
        correction_text = "\n".join(
            f"- \"{c['message_text'][:100]}\" was classified as {c['primary_dimension'] or 'none'}, "
            f"corrected to {c['user_correction']}"
            for c in corrections
        )

        current_keywords = json.dumps(
            {d: kws[:10] for d, kws in DIMENSION_KEYWORDS.items()},
            indent=2,
        )

        ai = get_ai_client()
        model = get_ai_model()
        response = await ai.messages.create(
            model=model,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": (
                    "Based on these recent misclassifications and corrections, suggest new keywords "
                    "for each life dimension. Return ONLY a JSON object mapping dimension names to "
                    "arrays of new keyword strings. Each keyword should be lowercase.\n\n"
                    f"Current keywords (sample):\n{current_keywords}\n\n"
                    f"Recent corrections:\n{correction_text}\n\n"
                    "Suggest 3-8 new keywords per dimension that would have caught these "
                    "misclassifications. Only suggest keywords that are clearly associated "
                    "with one dimension. Reply with ONLY the JSON object."
                ),
            }],
        )

        try:
            from core.token_logger import log_token_usage
            log_token_usage(response, caller="scheduled_keyword_expansion", model=model)
        except Exception:
            pass

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        suggestions = json.loads(raw)

        # Insert suggestions into keyword_feedback
        inserted = 0
        for dim, keywords in suggestions.items():
            matched_dim = None
            for known_dim in DIMENSION_KEYWORDS:
                if known_dim.lower() == dim.lower() or known_dim == dim:
                    matched_dim = known_dim
                    break
            if not matched_dim:
                continue

            for kw in keywords:
                if not isinstance(kw, str) or len(kw) < 2:
                    continue
                try:
                    await query(
                        "INSERT OR IGNORE INTO keyword_feedback (dimension, keyword, source, success_count) "
                        "VALUES (?, ?, 'llm_suggested', 1)",
                        (matched_dim, kw.lower()),
                    )
                    inserted += 1
                except Exception:
                    pass

        logger.info("Keyword expansion: %d suggestions from %d corrections", inserted, len(corrections))
        _record_job_run("keyword_expansion")

        # Reload dynamic keywords into the classifier
        try:
            from handlers.capture import get_classifier
            new_keywords = load_dynamic_keywords()
            get_classifier().update_keywords(new_keywords)
            logger.info("Classifier keywords hot-reloaded")
        except Exception:
            logger.warning("Could not hot-reload classifier keywords")

    except Exception:
        logger.exception("Keyword expansion job failed")


async def job_weekly_review(context: CallbackContext):
    """Weekly Sunday 7pm: GTD weekly review."""
    try:
        logger.info("Running weekly review job")
        result = await _call_claude("weekly-review")
        await _send_to_topic(context.bot, "brain-daily", result)
        _record_job_run("weekly_review")
    except Exception:
        logger.exception("Weekly review job failed")


async def job_db_backup(context: CallbackContext):
    """Daily 4am: Backup brain.db to data/backups/, keep last 7 copies."""
    try:
        from pathlib import Path
        from core.async_utils import run_in_executor

        backup_dir = Path(DB_PATH).parent / "backups"
        backup_dir.mkdir(exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        dest = backup_dir / f"brain-{today}.db"

        def _do_backup():
            src_conn = sqlite3.connect(str(DB_PATH))
            dst_conn = sqlite3.connect(str(dest))
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

        await run_in_executor(_do_backup)
        logger.info("DB backup created: %s", dest)

        # Prune old backups (keep last 7)
        backups = sorted(backup_dir.glob("brain-*.db"))
        for old in backups[:-7]:
            old.unlink()
            logger.info("Pruned old backup: %s", old.name)

        _record_job_run("db_backup")
    except Exception:
        logger.exception("DB backup job failed")


async def job_daily_engagement(context: CallbackContext):
    """Daily 5:30am: Compute and store daily engagement metrics."""
    try:
        from core.async_utils import run_in_executor
        from core.engagement import compute_daily_metrics, save_daily_metrics
        logger.info("Running daily engagement metrics job")
        metrics = await run_in_executor(compute_daily_metrics)
        await run_in_executor(save_daily_metrics, metrics)
        logger.info("Engagement metrics saved: score=%.1f", metrics.get("engagement_score", 0))
        _record_job_run("daily_engagement")
    except Exception:
        logger.exception("Daily engagement job failed")


async def job_dimension_signals(context: CallbackContext):
    """Daily 5:45am: Compute dimension momentum signals."""
    try:
        from core.async_utils import run_in_executor
        from core.dimension_signals import compute_dimension_signals
        logger.info("Running dimension signals job")
        signals = await run_in_executor(compute_dimension_signals)
        logger.info("Dimension signals computed: %d dimensions", len(signals))
        _record_job_run("dimension_signals")
    except Exception:
        logger.exception("Dimension signals job failed")


async def job_weekly_brain_level(context: CallbackContext):
    """Weekly Sunday 6:30pm: Compute Brain Level score."""
    try:
        from core.async_utils import run_in_executor
        from core.dimension_signals import compute_brain_level
        logger.info("Running weekly brain level job")
        result = await run_in_executor(compute_brain_level)
        logger.info("Brain Level computed: level=%d", result.get("level", 0))
        _record_job_run("weekly_brain_level")
    except Exception:
        logger.exception("Weekly brain level job failed")


async def job_resolve_pending_captures(context: CallbackContext):
    """Every 5 min: auto-file pending captures that timed out."""
    try:
        from config import BOUNCER_TIMEOUT_MINUTES

        # Guard: skip if pending_captures table hasn't been created yet
        table_check = await query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_captures'"
        )
        if not table_check:
            return

        rows = await query(
            "SELECT id, message_text, message_ts, primary_dimension, chat_id, "
            "bouncer_dm_ts, bouncer_dm_channel "
            "FROM pending_captures WHERE status = 'pending' "
            "AND created_at < datetime('now', ?)",
            (f"-{BOUNCER_TIMEOUT_MINUTES} minutes",),
        )

        if not rows:
            return

        logger.info("Auto-filing %d timed-out pending captures", len(rows))
        for row in rows:
            try:
                await execute(
                    "UPDATE pending_captures SET status = 'timeout', "
                    "user_selection = primary_dimension, resolved_at = datetime('now') "
                    "WHERE id = ?",
                    (row["id"],),
                )

                # Route via normal path
                from handlers.capture import process_bouncer_resolution
                await process_bouncer_resolution(
                    context.bot,
                    row["message_text"],
                    row["message_ts"],
                    row["primary_dimension"] or "Systems & Environment",
                    row["chat_id"],
                )
            except Exception:
                logger.exception("Failed to resolve pending capture id=%d", row["id"])
    except Exception:
        logger.exception("Error in job_resolve_pending_captures")


async def job_rolling_memo(context: CallbackContext):
    """Daily 9:30pm: Generate structured daily memo for context compression."""
    try:
        logger.info("Running rolling memo job")
        result = await _call_claude("rolling-memo")
        if result:
            from core.rolling_memo import append_to_rolling_memo
            from core.async_utils import run_in_executor
            success = await run_in_executor(append_to_rolling_memo, result)
            if success:
                logger.info("Rolling memo appended")
            else:
                logger.warning("Rolling memo append failed")
        _record_job_run("rolling_memo")
    except Exception as e:
        logger.exception("Rolling memo job failed")
        await _notify_job_failure(context.bot, "rolling_memo", e)


async def job_weekly_connections(context: CallbackContext):
    """Weekly connections analysis — finds bridges between recent captures."""
    try:
        rows = await query(
            """SELECT DISTINCT json_each.value AS dimension
               FROM captures_log, json_each(captures_log.dimensions_json)
               WHERE created_at > datetime('now', '-7 days')
                 AND json_each.value IS NOT NULL AND json_each.value != ''
               LIMIT 6"""
        )
        if not rows or len(rows) < 2:
            logger.info("Not enough recent captures for connections analysis")
            _record_job_run("weekly_connections")
            return

        topics = [r["dimension"] for r in rows]
        # Pick two most different topics for connection
        user_input = f'"{topics[0]}" and "{topics[-1]}"'

        result = await _call_claude("connect", user_input)
        await _send_to_topic(context.bot, "brain-insights", result)
        _record_job_run("weekly_connections")
    except Exception as e:
        logger.exception("weekly_connections failed")
        await _notify_job_failure(context.bot, "weekly_connections", e)


async def job_weekly_contradiction_scan(context: CallbackContext):
    """Weekly contradiction scan — finds conflicting statements in recent captures."""
    try:
        rows = await query(
            """SELECT message_text, created_at, dimensions_json FROM captures_log
               WHERE created_at > datetime('now', '-14 days')
               ORDER BY created_at DESC LIMIT 30"""
        )
        if not rows or len(rows) < 5:
            logger.info("Not enough recent captures for contradiction scan")
            _record_job_run("weekly_contradiction_scan")
            return

        captures_text = "\n".join(
            f"[{r['created_at'][:10]}] ({r.get('dimensions_json', '[]')}): {r['message_text'][:150]}"
            for r in rows
        )

        prompt = (
            "Analyze these recent captures for contradictions, inconsistencies, "
            "or stated intentions that conflict with later actions. Only flag "
            "genuine contradictions, not normal evolution of thinking.\n\n"
            f"RECENT CAPTURES:\n{captures_text}\n\n"
            "If you find contradictions, list each one with:\n"
            "- The contradicting statements (with dates)\n"
            "- Why this matters\n"
            "- A question for the user to reflect on\n\n"
            "If no meaningful contradictions found, say so briefly."
        )

        ai = get_ai_client()
        if ai is None:
            logger.info("No AI client configured — skipping contradiction scan")
            return
        model = get_ai_model()
        response = await ai.messages.create(
            model=model,
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": "You are a thoughtful analyst reviewing someone's personal notes "
                        "for internal contradictions. Be gentle but honest.",
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            from core.token_logger import log_token_usage
            log_token_usage(response, caller="scheduled_contradiction_scan", model=model)
        except Exception:
            pass

        result = response.content[0].text

        if "no meaningful contradictions" not in result.lower():
            header = "<b>Weekly Contradiction Scan</b>\n\n"
            await _send_to_topic(context.bot, "brain-insights", header + html.escape(result))

        _record_job_run("weekly_contradiction_scan")
    except Exception as e:
        logger.exception("weekly_contradiction_scan failed")
        await _notify_job_failure(context.bot, "weekly_contradiction_scan", e)


async def job_graph_maintenance(context: CallbackContext):
    """Weekly Sunday 4:30am: Graph health check — find orphans and suggest connections."""
    try:
        logger.info("Running graph maintenance job")
        from core.graph_maintenance import run_maintenance
        from core.async_utils import run_in_executor

        result = await run_in_executor(run_maintenance)

        if result and result.get("orphans"):
            orphan_count = result.get("total_orphans", len(result["orphans"]))
            density_info = result.get("density", {})
            density_pct = density_info.get("density", 0)

            text = (
                f"<b>Graph Health Check</b>\n\n"
                f"Orphan documents: <b>{orphan_count}</b>\n"
                f"Stale concepts: <b>{len(result.get('stale_concepts', []))}</b>\n"
                f"Graph density: <b>{density_pct:.1%}</b>"
            )
            await _send_to_topic(context.bot, "brain-dashboard", text)

        _record_job_run("graph_maintenance")
    except Exception:
        logger.exception("Graph maintenance job failed")


async def job_system_health_check(context: CallbackContext):
    """Daily 5:30am: System health check — API status, graph quality, engagement."""
    try:
        from core.db_connection import get_connection

        lines = ["<b>System Health Check</b>\n"]

        # 1. AI Provider status
        from core.ai_client import _detect_provider
        provider = _detect_provider()
        ai = get_ai_client()
        if ai:
            lines.append(f"AI: {provider} ({get_ai_model()}) — OK")
        else:
            lines.append("AI: NOT CONFIGURED")

        # 2. Notion status
        try:
            import os
            token = os.environ.get("NOTION_TOKEN", "")
            if token:
                from notion_client import Client
                Client(auth=token).users.me()
                lines.append("Notion: OK")
            else:
                lines.append("Notion: NO TOKEN")
        except Exception as e:
            lines.append(f"Notion: FAILED — {str(e)[:50]}")

        # 3. Graph stats
        with get_connection() as conn:
            edges = conn.execute(
                "SELECT edge_type, count(*) FROM vault_edges GROUP BY edge_type ORDER BY count(*) DESC"
            ).fetchall()
            total_edges = sum(c for _, c in edges)
            edge_str = ", ".join(f"{t}:{c}" for t, c in edges)
            nodes = conn.execute(
                "SELECT count(*) FROM vault_nodes WHERE node_type='document'"
            ).fetchone()[0]
            chunks = conn.execute("SELECT count(*) FROM vault_chunks").fetchone()[0]

        lines.append(f"\nGraph: {nodes} docs, {total_edges} edges ({edge_str})")
        lines.append(f"Chunks: {chunks}")

        # 4. Engagement (7-day)
        with get_connection() as conn:
            journal_7d = conn.execute(
                "SELECT count(*) FROM journal_entries WHERE date >= date('now', '-7 days')"
            ).fetchone()[0]
            captures_7d = conn.execute(
                "SELECT count(*) FROM captures_log WHERE created_at >= datetime('now', '-7 days')"
            ).fetchone()[0]

        lines.append(f"\n7-day: {journal_7d} journal entries, {captures_7d} captures")

        # 5. Edge type coverage warning
        edge_types_present = {t for t, _ in edges}
        expected = {"wikilink", "semantic_similarity", "tag_shared", "icor_affinity"}
        missing = expected - edge_types_present
        if missing:
            lines.append(f"\n⚠️ Missing edge types: {', '.join(missing)}")

        text = "\n".join(lines)
        await _send_to_topic(context.bot, "brain-dashboard", text)
        _record_job_run("system_health_check")
    except Exception:
        logger.exception("System health check failed")


async def job_graduation_proposals(context: CallbackContext):
    """Weekly Sunday 5:15am: Detect and propose concept graduations."""
    try:
        logger.info("Running graduation proposals job")
        from core.graduation_detector import detect_graduation_candidates

        # Expire old pending proposals (14-day TTL)
        from core.db_connection import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE graduation_proposals SET status='expired', resolved_at=datetime('now') "
                "WHERE status='pending' AND proposed_at <= datetime('now', '-14 days')"
            )
            # Un-snooze overdue snoozed proposals
            conn.execute(
                "UPDATE graduation_proposals SET status='pending' "
                "WHERE status='snoozed' AND snooze_until <= datetime('now')"
            )
            conn.commit()

        candidates = await detect_graduation_candidates()
        if not candidates:
            logger.info("No graduation candidates found")
            _record_job_run("graduation_proposals")
            return

        # Hard cap: 1 proposal per run
        candidate = candidates[0]

        await execute(
            "INSERT OR IGNORE INTO graduation_proposals "
            "(cluster_hash, proposed_title, proposed_dimension, source_capture_ids, source_texts) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                candidate["cluster_hash"],
                candidate["proposed_title"],
                candidate["dimension"],
                json.dumps(candidate["source_ids"]),
                json.dumps(candidate["source_texts"]),
            ),
        )

        # Query unconditionally for unsent proposals (handles both new inserts
        # and ignored duplicates where lastrowid=0)
        unsent = await query(
            "SELECT * FROM graduation_proposals "
            "WHERE cluster_hash=? AND message_id IS NULL AND status='pending'",
            (candidate["cluster_hash"],),
        )
        if unsent:
            from handlers.graduation import format_graduation_proposal

            proposal = unsent[0]
            text, kb = format_graduation_proposal(
                {
                    **proposal,
                    "capture_count": candidate["capture_count"],
                    "days_span": candidate["days_span"],
                }
            )
            msgs = await _send_to_topic(
                context.bot, "brain-insights", text, keyboard=kb,
            )
            if msgs:
                last_msg = msgs[-1] if isinstance(msgs, list) else msgs
                await execute(
                    "UPDATE graduation_proposals SET message_id=? WHERE id=?",
                    (last_msg.message_id, proposal["id"]),
                )

        _record_job_run("graduation_proposals")
    except Exception as e:
        logger.exception("Graduation proposals job failed")
        await _notify_job_failure(context.bot, "graduation_proposals", e)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_jobs(job_queue):
    """Register all scheduled jobs with PTB's JobQueue. Called from app.py."""

    # Daily 4am: Database backup
    job_queue.run_daily(job_db_backup, time=time(4, 0, tzinfo=CST), name="db_backup")

    # Daily 5am: Vault + journal re-index
    job_queue.run_daily(job_vault_reindex, time=time(5, 0, tzinfo=CST), name="vault_reindex")

    # Daily 5:30am: System health check (after vault reindex)
    job_queue.run_daily(job_system_health_check, time=time(5, 30, tzinfo=CST), name="system_health_check")

    # Daily 5:30am: Engagement metrics (after vault reindex)
    job_queue.run_daily(job_daily_engagement, time=time(5, 30, tzinfo=CST), name="daily_engagement")

    # Daily 5:45am: Dimension signals (after engagement)
    job_queue.run_daily(job_dimension_signals, time=time(5, 45, tzinfo=CST), name="dimension_signals")

    # Daily 6am, 6pm: Dashboard refresh
    job_queue.run_daily(job_dashboard_refresh, time=time(6, 0, tzinfo=CST), name="dashboard_refresh_am")
    job_queue.run_daily(job_dashboard_refresh, time=time(18, 0, tzinfo=CST), name="dashboard_refresh_pm")

    # Daily 7am: Morning briefing
    job_queue.run_daily(job_morning_briefing, time=time(7, 0, tzinfo=CST), name="morning_briefing")

    # Daily 9pm: Evening review prompt
    job_queue.run_daily(job_evening_prompt, time=time(21, 0, tzinfo=CST), name="evening_prompt")

    # Daily 9:30pm: Rolling memo (after evening prompt, before Notion sync)
    job_queue.run_daily(job_rolling_memo, time=time(21, 30, tzinfo=CST), name="rolling_memo")

    # Daily 10pm: Notion sync (silent)
    job_queue.run_daily(job_notion_sync, time=time(22, 0, tzinfo=CST), name="notion_sync")

    # Weekly Sunday 2am: Keyword expansion from corrections
    job_queue.run_daily(
        job_keyword_expansion,
        time=time(2, 0, tzinfo=CST),
        days=(6,),  # 6 = Sunday
        name="keyword_expansion",
    )

    # Weekly Sunday 4:30am: Graph maintenance health check (after DB backup at 4am)
    job_queue.run_daily(
        job_graph_maintenance,
        time=time(4, 30, tzinfo=CST),
        days=(6,),  # 6 = Sunday
        name="graph_maintenance",
    )

    # Weekly Sunday 5:15am: Graduation proposals (after vault reindex at 5am)
    job_queue.run_daily(
        job_graduation_proposals,
        time=time(5, 15, tzinfo=CST),
        days=(6,),  # 6 = Sunday
        name="graduation_proposals",
    )

    # Weekly Sunday 6pm: Drift report
    job_queue.run_daily(
        job_drift_report,
        time=time(18, 0, tzinfo=CST),
        days=(6,),
        name="drift_report",
    )

    # Weekly Sunday 6:30pm: Brain Level score
    job_queue.run_daily(
        job_weekly_brain_level,
        time=time(18, 30, tzinfo=CST),
        days=(6,),
        name="weekly_brain_level",
    )

    # Weekly Sunday 7pm: GTD weekly review
    job_queue.run_daily(
        job_weekly_review,
        time=time(19, 0, tzinfo=CST),
        days=(6,),
        name="weekly_review",
    )

    # Weekly Monday 9am: Project summary
    job_queue.run_daily(
        job_weekly_project_summary,
        time=time(9, 0, tzinfo=CST),
        days=(0,),  # 0 = Monday
        name="weekly_project_summary",
    )

    # Bi-weekly Wednesday 2pm: Pattern synthesis (counter-based in DB)
    job_queue.run_daily(
        job_emerge_biweekly,
        time=time(14, 0, tzinfo=CST),
        days=(2,),  # 2 = Wednesday
        name="emerge_biweekly",
    )

    # Weekly Wednesday 3pm: Connections analysis (after emerge)
    job_queue.run_daily(
        job_weekly_connections,
        time=time(15, 0, tzinfo=CST),
        days=(2,),  # 2 = Wednesday
        name="weekly_connections",
    )

    # Weekly Sunday 5pm: Contradiction scan
    job_queue.run_daily(
        job_weekly_contradiction_scan,
        time=time(17, 0, tzinfo=CST),
        days=(6,),  # 6 = Sunday
        name="weekly_contradiction_scan",
    )

    # Monthly 1st at 10am: Resource digest (daily check with day guard)
    job_queue.run_daily(
        job_monthly_resource_digest,
        time=time(10, 0, tzinfo=CST),
        name="monthly_resource_digest",
    )

    # Every 5 min: Resolve timed-out pending captures
    job_queue.run_repeating(
        job_resolve_pending_captures,
        interval=300,  # 5 minutes
        first=60,  # start after 1 minute
        name="resolve_pending_captures",
    )

    job_names = [j.name for j in job_queue.jobs()]
    logger.info("Registered %d scheduled jobs: %s", len(job_names), job_names)

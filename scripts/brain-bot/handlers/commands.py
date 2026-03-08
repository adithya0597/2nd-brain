"""Command handlers for Second Brain Telegram bot.

Each command shows edit-in-place progress, then posts results to the
appropriate forum topic (or DM).
"""
import html
import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    DB_PATH,
    GROUP_CHAT_ID,
    NOTION_COLLECTIONS,
    NOTION_REGISTRY_PATH,
    NOTION_TOKEN,
    OWNER_TELEGRAM_ID,
    TOPICS,
    VAULT_PATH,
)
from core.ai_client import get_ai_client, get_ai_model
from core.async_utils import run_in_executor
from core.context_loader import (
    build_claude_messages,
    gather_command_context,
    load_command_prompt,
    load_system_context,
)
from core.db_ops import (
    get_attention_scores,
    get_cost_summary,
    get_neglected_elements,
    get_pending_actions,
    get_recent_journal,
)
from core.formatter import (
    format_cost_report,
    format_dashboard,
    format_error,
    format_help,
    format_sync_report,
)
from core.message_utils import send_long_message
from core.notion_client import NotionClientWrapper
from core.notion_sync import NotionSync
from core.vault_ops import (
    append_to_daily_note,
    create_concept_file,
    create_report_file,
    create_weekly_plan,
    ensure_daily_note,
)

logger = logging.getLogger(__name__)

# Commands that auto-save reports to vault
_AUTO_VAULT_WRITE_COMMANDS = {
    "drift", "emerge", "ideas", "ghost", "challenge",
    "trace", "connect", "engage",
}

# telegram_command -> (brain_command, topic_name or None for DM)
_COMMAND_MAP = {
    "today": ("today", "brain-daily"),
    "close": ("close-day", "brain-daily"),
    "drift": ("drift", "brain-insights"),
    "emerge": ("emerge", "brain-insights"),
    "ideas": ("ideas", "brain-insights"),
    "schedule": ("schedule", "brain-daily"),
    "ghost": ("ghost", "brain-insights"),
    "projects": ("projects", "brain-daily"),
    "resources": ("resources", "brain-daily"),
    "context": ("context-load", None),
    "trace": ("trace", "brain-insights"),
    "connect": ("connect", "brain-insights"),
    "challenge": ("challenge", "brain-insights"),
    "graduate": ("graduate", "brain-insights"),
    "review": ("weekly-review", "brain-daily"),
    "process_meeting": ("process-meeting", "brain-daily"),
    "engage": ("engage", "brain-daily"),
}


def _owner_only(update: Update) -> bool:
    """Return True if the update is from the bot owner (or no owner configured)."""
    if not OWNER_TELEGRAM_ID:
        return True
    return update.effective_user is not None and update.effective_user.id == OWNER_TELEGRAM_ID


def _write_command_output_to_vault(brain_command: str, result_text: str, user_input: str):
    """Write AI command output back to the vault (sync, called via run_in_executor)."""
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        if brain_command == "close-day":
            ensure_daily_note(today)
            append_to_daily_note(today, f"\n## Evening Review\n\n{result_text[:3000]}")
            try:
                from core.journal_indexer import run_full_index
                run_full_index()
            except Exception:
                logger.debug("Journal re-index skipped")

        elif brain_command == "today":
            ensure_daily_note(today)
            append_to_daily_note(today, f"\n## Morning Plan\n\n{result_text[:3000]}")

        elif brain_command == "schedule":
            create_weekly_plan(result_text, date=today)

        elif brain_command in _AUTO_VAULT_WRITE_COMMANDS:
            create_report_file(brain_command, result_text)

        elif brain_command == "graduate":
            create_report_file("graduate", result_text)
            try:
                from core.output_parser import parse_graduate_output
                from core.db_ops import insert_concept_metadata
                import asyncio

                concepts = parse_graduate_output(result_text)
                loop = asyncio.new_event_loop()
                for concept in concepts:
                    try:
                        file_path = create_concept_file(
                            name=concept.title,
                            summary=concept.summary,
                            source_notes=concept.source_dates,
                            icor_elements=concept.icor_elements,
                            status=concept.status,
                        )
                        rel_path = str(file_path.relative_to(VAULT_PATH))
                        loop.run_until_complete(insert_concept_metadata(
                            title=concept.title,
                            file_path=rel_path,
                            icor_elements=concept.icor_elements,
                            first_mentioned=concept.first_mentioned,
                            last_mentioned=concept.last_mentioned,
                            mention_count=concept.mention_count,
                            summary=concept.summary,
                            status=concept.status,
                        ))
                        logger.info("Graduated concept: %s -> %s", concept.title, file_path)
                    except Exception:
                        logger.exception("Failed to create concept: %s", concept.title)
                loop.close()
                if concepts:
                    logger.info("Graduated %d concepts from /graduate", len(concepts))
            except Exception:
                logger.exception("Failed to parse graduate output for concept creation")

    except Exception:
        logger.exception("Error writing %s output to vault", brain_command)


async def _run_ai_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    brain_command: str,
    topic_name: str | None,
):
    """Gather context, call Claude, write to vault, post result."""
    user_input = " ".join(context.args) if context.args else ""
    msg = await update.message.reply_text("\u23f3 Gathering context...")

    try:
        # Stage 1: Gather context
        ctx = await gather_command_context(brain_command, user_input=user_input)
        await msg.edit_text("\U0001f9e0 Asking Claude...")

        # Stage 2: Call Claude (async client)
        system_ctx = load_system_context()
        prompt = load_command_prompt(brain_command)
        messages = build_claude_messages(brain_command, user_input, ctx)

        ai = get_ai_client()
        if not ai:
            await msg.edit_text("\u274c Anthropic API key not configured.")
            return

        response = await ai.messages.create(
            model=get_ai_model(),
            max_tokens=4096,
            system=[
                {"type": "text", "text": system_ctx, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
            ],
            messages=messages,
        )

        result_text = response.content[0].text

        # Log token usage
        try:
            from core.token_logger import log_token_usage
            log_token_usage(response, caller=f"command_{brain_command}", model=get_ai_model())
        except Exception:
            pass

        # Write to vault (sync I/O — offload to executor)
        await run_in_executor(_write_command_output_to_vault, brain_command, result_text, user_input)

        # Delete progress message
        await msg.delete()

        # Determine target chat and topic
        if topic_name and TOPICS.get(topic_name) and GROUP_CHAT_ID:
            target_chat = GROUP_CHAT_ID
            target_topic = TOPICS[topic_name]
        else:
            target_chat = update.effective_user.id
            target_topic = None

        # Build save-to-vault keyboard for non-auto-saved reports
        keyboard = None
        if brain_command in ("projects", "resources"):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "\U0001f4be Save to Vault",
                    callback_data=json.dumps(
                        {"a": "save_vault", "cmd": brain_command},
                        separators=(",", ":"),
                    ),
                )
            ]])

        # Send result (HTML-escaped AI text + italic footer)
        safe_text = html.escape(result_text)
        footer = f"\n\n<i>/{brain_command} | {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
        await send_long_message(
            context.bot, target_chat, safe_text + footer,
            reply_markup=keyboard, topic_id=target_topic,
        )

    except Exception:
        logger.exception("Error running AI command: %s", brain_command)
        try:
            error_text, _ = format_error(f"Failed to execute /{brain_command}. Check bot logs.")
            await msg.edit_text(error_text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send error message")


async def _handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick SQLite-only status dashboard (no AI call)."""
    if not _owner_only(update):
        return

    msg = await update.message.reply_text("\u23f3 Fetching status...")
    try:
        pending = await get_pending_actions()
        neglected = await get_neglected_elements()
        attention = await get_attention_scores()
        recent = await get_recent_journal(days=1)

        journal_today = "Yes" if recent else "No"

        icor_data: dict[str, list] = {}
        for score in attention:
            dim = score.get("dimension", "Unknown")
            if dim not in icor_data:
                icor_data[dim] = []
            icor_data[dim].append(score)

        text, keyboard = format_dashboard(icor_data, [], pending)

        # Add neglected elements
        if neglected:
            neglected_lines = "\n".join(
                f"\u2022 <b>{html.escape(n['name'])}</b> ({html.escape(n.get('dimension', 'N/A'))}) \u2014 "
                f"{int(n.get('days_since') or 0)} days silent"
                for n in neglected[:5]
            )
            text += f"\n\n<b>Neglected Elements:</b>\n{neglected_lines}"

        # Add quick stats after the header
        stats = (
            f"\n<b>Quick Stats:</b>\n"
            f"\u2022 Pending actions: {len(pending)}\n"
            f"\u2022 Journaled today: {journal_today}\n"
            f"\u2022 Neglected elements: {len(neglected)}"
        )
        # Insert after first line
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[:first_nl] + "\n" + stats + text[first_nl:]
        else:
            text = text + "\n" + stats

        await msg.delete()

        target_chat = GROUP_CHAT_ID if GROUP_CHAT_ID else update.effective_user.id
        target_topic = TOPICS.get("brain-dashboard")
        await send_long_message(
            context.bot, target_chat, text,
            reply_markup=keyboard, topic_id=target_topic,
        )

    except Exception:
        logger.exception("Error running status command")
        await msg.edit_text("\u274c Failed to fetch status.")


async def _handle_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run Python-native Notion sync."""
    if not _owner_only(update):
        return

    if not NOTION_TOKEN:
        error_text, _ = format_error("NOTION_TOKEN not configured. Set it in .env to enable Notion sync.")
        await update.message.reply_text(error_text, parse_mode="HTML")
        return

    msg = await update.message.reply_text("\u23f3 Running Notion sync...")
    try:
        user_input = " ".join(context.args) if context.args else ""
        entity_types = [t.strip() for t in user_input.split(",") if t.strip()] if user_input else []

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
            if entity_types:
                result = await syncer.run_selective_sync(entity_types)
            else:
                result = await syncer.run_full_sync()
        finally:
            await notion.close()

        await msg.delete()
        text, keyboard = format_sync_report(result)
        await send_long_message(
            context.bot, update.effective_user.id, text,
            reply_markup=keyboard,
        )

    except Exception:
        logger.exception("Error running sync command")
        error_text, _ = format_error("Notion sync failed. Check bot logs.")
        await msg.edit_text(error_text, parse_mode="HTML")


async def _handle_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Query API cost data and post dashboard (no AI call)."""
    if not _owner_only(update):
        return

    msg = await update.message.reply_text("\u23f3 Fetching cost data...")
    try:
        user_input = " ".join(context.args) if context.args else ""
        days = int(user_input.strip()) if user_input.strip().isdigit() else 30

        data = await get_cost_summary(days)
        text, keyboard = format_cost_report(data, days)

        await msg.delete()

        target_chat = GROUP_CHAT_ID if GROUP_CHAT_ID else update.effective_user.id
        target_topic = TOPICS.get("brain-dashboard")
        await send_long_message(
            context.bot, target_chat, text,
            reply_markup=keyboard, topic_id=target_topic,
        )

    except Exception:
        logger.exception("Error running cost command")
        await msg.edit_text("\u274c Failed to fetch cost data.")


async def _handle_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hybrid search — fast local search or AI-powered."""
    if not _owner_only(update):
        return

    user_input = " ".join(context.args) if context.args else ""
    if not user_input:
        await update.message.reply_text(
            "Usage: <code>/find query</code> or <code>/find --ai query</code>",
            parse_mode="HTML",
        )
        return

    # Check for --ai flag
    if user_input.startswith("--ai "):
        ai_query = user_input[5:].strip()
        await _run_ai_command(update, context, "find", None)
        return

    msg = await update.message.reply_text("\U0001f50d Searching...")
    try:
        from core.search import hybrid_search
        from core.formatter import format_search_results

        response = await run_in_executor(hybrid_search, user_input, limit=15)

        if not response.results:
            safe_query = html.escape(user_input)
            text = (
                f'No results found for <b>"{safe_query}"</b>.\n\n'
                f"Try:\n\u2022 Different keywords\n\u2022 Broader search terms\n"
                f"\u2022 <code>/find --ai {safe_query}</code> for AI-powered search"
            )
            await msg.edit_text(text, parse_mode="HTML")
            return

        text, keyboard = format_search_results(
            query=user_input,
            results=response.results,
            channels_used=response.channels_used,
            total=response.total_candidates,
        )

        await msg.delete()
        await send_long_message(
            context.bot, update.effective_user.id, text,
            reply_markup=keyboard,
        )

    except Exception:
        logger.exception("Error running fast search")
        error_text, _ = format_error(f'Search failed for "{user_input}". Check bot logs.')
        await msg.edit_text(error_text, parse_mode="HTML")


async def _handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all available commands."""
    if not _owner_only(update):
        return

    text, keyboard = format_help()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


def register(application: Application):
    """Register all command handlers."""

    # AI-powered commands from the command map
    for cmd_name, (brain_cmd, topic_name) in _COMMAND_MAP.items():
        def _make_handler(bc, tn):
            async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not _owner_only(update):
                    return
                await _run_ai_command(update, context, bc, tn)
            return handler

        application.add_handler(CommandHandler(cmd_name, _make_handler(brain_cmd, topic_name)))

    # Special commands (no AI or custom logic)
    application.add_handler(CommandHandler("status", _handle_status))
    application.add_handler(CommandHandler("sync", _handle_sync))
    application.add_handler(CommandHandler("cost", _handle_cost))
    application.add_handler(CommandHandler("find", _handle_find))
    application.add_handler(CommandHandler("help", _handle_help))

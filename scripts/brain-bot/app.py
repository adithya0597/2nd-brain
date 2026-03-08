"""Second Brain Telegram Bot — Entry Point.

python-telegram-bot v21 application that bridges Telegram with the Second Brain
vault, SQLite database, and Anthropic API.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    Defaults,
    filters,
    MessageHandler,
)

from config import (
    GROUP_CHAT_ID,
    OWNER_TELEGRAM_ID,
    TELEGRAM_BOT_TOKEN,
    TOPICS,
)
from core.async_utils import shutdown as shutdown_executor

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

console = logging.StreamHandler()
console.setFormatter(formatter)
root_logger.addHandler(console)

file_handler = RotatingFileHandler(
    log_dir / "brain-bot.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("brain-bot")

# Timezone for scheduled jobs
CST = ZoneInfo("America/Chicago")


# ---------------------------------------------------------------------------
# Owner-only filter
# ---------------------------------------------------------------------------
class OwnerFilter(filters.MessageFilter):
    """Only allow messages from the bot owner."""

    def filter(self, message):
        if not OWNER_TELEGRAM_ID:
            return True  # No restriction configured
        user = message.from_user
        if user is None:
            return False
        return user.id == OWNER_TELEGRAM_ID


owner_filter = OwnerFilter()


# ---------------------------------------------------------------------------
# Startup: post_init callback
# ---------------------------------------------------------------------------
async def post_init(application: Application) -> None:
    """Run after the Application has been initialized and the bot is ready."""
    logger.info("Running post_init startup sequence...")

    # 1. Register bot commands with Telegram
    commands = [
        BotCommand("today", "Morning review and daily briefing"),
        BotCommand("close", "Evening review and day wrap-up"),
        BotCommand("drift", "Alignment drift analysis"),
        BotCommand("emerge", "Surface unnamed patterns"),
        BotCommand("ideas", "Generate actionable ideas"),
        BotCommand("schedule", "Energy-aware weekly planning"),
        BotCommand("ghost", "Digital twin response"),
        BotCommand("status", "Quick status dashboard"),
        BotCommand("sync", "Sync with Notion"),
        BotCommand("projects", "Active project dashboard"),
        BotCommand("resources", "Knowledge base catalog"),
        BotCommand("trace", "Concept evolution timeline"),
        BotCommand("connect", "Serendipity engine"),
        BotCommand("challenge", "Red-team a belief"),
        BotCommand("graduate", "Promote journal themes"),
        BotCommand("context", "Load session context"),
        BotCommand("find", "Semantic vault search"),
        BotCommand("help", "List available commands"),
        BotCommand("engage", "Engagement analysis"),
        BotCommand("dashboard", "Full ICOR dashboard with quick actions"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Registered %d bot commands with Telegram", len(commands))

    # 2. Register handler modules
    try:
        from handlers import register_all
        register_all(application)
        logger.info("All handler modules registered")
    except Exception as e:
        logger.warning("Handler registration failed (bot will run without handlers): %s", e)

    # 3. Load dynamic keywords into classifier
    try:
        from config import load_dynamic_keywords
        keywords = load_dynamic_keywords()
        logger.info("Dynamic keywords loaded: %s", {d: len(v) for d, v in keywords.items()})
    except Exception:
        logger.info("Dynamic keywords unavailable — using seed keywords")

    # 4. Run vault + journal indexers
    try:
        from core.vault_indexer import run_full_index as index_vault
        from core.journal_indexer import run_full_index as index_journal
        vault_count = index_vault()
        journal_count = index_journal()
        logger.info("Startup index: %d vault files, %d journal entries", vault_count, journal_count)
    except Exception:
        logger.warning("Startup vault/journal indexing failed")

    # 5. Populate FTS5 index
    try:
        from config import DB_PATH, VAULT_PATH
        from core.fts_index import populate_fts
        fts_count = populate_fts(db_path=str(DB_PATH), vault_path=str(VAULT_PATH))
        logger.info("FTS5 index populated: %d files", fts_count)
    except Exception as e:
        logger.warning("FTS5 population failed (non-critical): %s", e)

    # 6. Populate vector embeddings
    try:
        from core.embedding_store import embed_all_files, seed_icor_embeddings
        embed_count = embed_all_files()
        icor_count = seed_icor_embeddings()
        logger.info("Vector embeddings: %d vault files, %d ICOR refs", embed_count, icor_count)
    except Exception as e:
        logger.warning("Vector embedding failed (non-critical): %s", e)

    # 7. Graph schema + ICOR affinity + community detection
    try:
        from core.graph_ops import ensure_icor_nodes
        from core.icor_affinity import rebuild_all_icor_edges
        from core.community import update_community_ids
        ensure_icor_nodes()
        affinity_count = rebuild_all_icor_edges()
        community_count = update_community_ids()
        logger.info(
            "Graph: ICOR nodes ensured, %d affinity edges, %d communities assigned",
            affinity_count, community_count,
        )
    except Exception as e:
        logger.warning("Graph/community setup failed (non-critical): %s", e)

    # 8. Register scheduled jobs with PTB's JobQueue
    try:
        from handlers.scheduled import register_jobs
        register_jobs(application.job_queue)
        logger.info("Scheduled jobs registered with JobQueue")
    except Exception as e:
        logger.warning("Failed to register scheduled jobs: %s", e)

    # 9. Health check
    _run_health_check()

    logger.info("Post-init complete. Bot is ready.")


# ---------------------------------------------------------------------------
# Shutdown: post_shutdown callback
# ---------------------------------------------------------------------------
async def post_shutdown(application: Application) -> None:
    """Clean up resources on shutdown."""
    logger.info("Shutting down executor pool...")
    shutdown_executor()
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def _run_health_check():
    """Verify critical subsystems on startup."""
    checks = {}

    # 1. Database accessible
    try:
        from core.db_connection import get_connection
        with get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as c FROM icor_hierarchy")
            row = cursor.fetchone()
            checks["database"] = f"OK ({row[0]} ICOR nodes)"
    except Exception as e:
        checks["database"] = f"FAIL: {e}"

    # 2. Vault path exists
    from config import VAULT_PATH
    checks["vault"] = "OK" if Path(VAULT_PATH).is_dir() else "FAIL: not found"

    # 3. Anthropic API key present
    from config import ANTHROPIC_API_KEY
    checks["anthropic_api"] = "OK" if ANTHROPIC_API_KEY else "WARN: not set (AI commands disabled)"

    # 4. Topic IDs configured
    checks["topics"] = f"OK ({len(TOPICS)} configured)" if TOPICS else "WARN: no topic IDs configured"

    # 5. Owner configured
    checks["owner"] = f"OK (ID: {OWNER_TELEGRAM_ID})" if OWNER_TELEGRAM_ID else "WARN: no owner restriction"

    # 6. Log results
    for name, status in checks.items():
        level = logging.WARNING if "FAIL" in status or "WARN" in status else logging.INFO
        logger.log(level, "Health check [%s]: %s", name, status)


# ---------------------------------------------------------------------------
# Unhandled message fallback (owner-only, in inbox topic)
# ---------------------------------------------------------------------------
async def _unhandled_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all for text messages in the inbox topic — will be handled by capture module."""
    # This is a placeholder. The capture handler module (Agent B) will replace this
    # with the actual classification + routing pipeline.
    logger.debug("Unhandled message from user %s", update.effective_user.id if update.effective_user else "unknown")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .defaults(Defaults(tzinfo=CST))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(8)
        .build()
    )

    # Add a low-priority catch-all for unhandled text messages (owner only)
    application.add_handler(
        MessageHandler(owner_filter & filters.TEXT & ~filters.COMMAND, _unhandled_message),
        group=999,  # Lowest priority — other handlers should be in lower group numbers
    )

    logger.info("Starting Second Brain bot with polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

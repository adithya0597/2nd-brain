"""Second Brain Slack Bot — Entry Point.

Bolt + Socket Mode app that bridges Slack with the Second Brain vault,
SQLite database, and Anthropic API.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import sys
import threading

import schedule
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import (
    CHANNELS,
    OWNER_SLACK_ID,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
)
from core.async_utils import shutdown as shutdown_executor

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Ensure log directory exists
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

# Configure logging with rotation
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Console handler
console = logging.StreamHandler()
console.setFormatter(formatter)
root_logger.addHandler(console)

# File handler with rotation (10MB, keep 5 backups)
file_handler = RotatingFileHandler(
    log_dir / "brain-bot.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("brain-bot")

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------
app = App(token=SLACK_BOT_TOKEN)


# ---------------------------------------------------------------------------
# Owner-only middleware
# ---------------------------------------------------------------------------
@app.middleware
def owner_only(body, next, logger):
    """Only process events from the bot owner."""
    if not OWNER_SLACK_ID:
        # No owner restriction configured
        next()
        return

    user = body.get("event", {}).get("user") or body.get("user_id") or body.get("user", {}).get("id", "")
    if user == OWNER_SLACK_ID or not user:
        next()
    else:
        logger.debug("Ignoring event from non-owner user: %s", user)


# ---------------------------------------------------------------------------
# Register handlers (imported lazily to avoid circular imports)
# ---------------------------------------------------------------------------
def resolve_channel_ids(client) -> dict[str, str]:
    """Resolve channel name -> ID mapping once at startup."""
    mapping: dict[str, str] = {}
    try:
        result = client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in result.get("channels", []):
            if ch["name"].startswith("brain-"):
                mapping[ch["name"]] = ch["id"]
    except Exception:
        logger.warning("conversations_list failed, falling back to name resolution")

    # Fallback: resolve by posting/deleting probe messages
    if not any(k.startswith("brain-") for k in mapping):
        logger.info("Resolving channel IDs by name (private channel workaround)")
        for name in CHANNELS:
            try:
                r = client.chat_postMessage(channel=f"#{name}", text="\u200b")
                mapping[name] = r["channel"]
                client.chat_delete(channel=r["channel"], ts=r["ts"])
            except Exception:
                logger.debug("Could not resolve channel #%s", name)

    logger.info("Resolved %d channel IDs at startup", len(mapping))
    return mapping


def register_handlers():
    """Import and register all handler modules."""
    try:
        from handlers import register_all
        register_all(app)
        logger.info("All handlers registered")

        # Pre-resolve channel IDs and distribute to handlers
        channel_ids = resolve_channel_ids(app.client)

        try:
            from handlers.capture import register as capture_register
            if hasattr(capture_register, "set_channel_ids"):
                capture_register.set_channel_ids(channel_ids)
        except Exception:
            logger.debug("Could not set capture channel IDs")

        try:
            from handlers.commands import set_channel_ids as cmd_set_ids
            cmd_set_ids(channel_ids)
        except Exception:
            logger.debug("Could not set commands channel IDs")

        # Load dynamic keywords into classifier at startup
        try:
            from config import load_dynamic_keywords
            from handlers.capture import get_classifier
            keywords = load_dynamic_keywords()
            get_classifier().update_keywords(keywords)
            logger.info("Classifier loaded with dynamic keywords")
        except Exception:
            logger.info("Dynamic keywords unavailable — using seed keywords")
    except ImportError:
        logger.warning("handlers package not found — running with no handlers")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def _run_scheduler():
    """Run the schedule loop in a daemon thread."""
    while True:
        schedule.run_pending()
        import time
        time.sleep(30)


def start_scheduler():
    """Start the scheduler daemon thread."""
    try:
        from handlers.scheduled import register_schedules
        register_schedules(app)
        logger.info("Scheduled jobs registered")
    except ImportError:
        logger.info("No scheduled handlers found — scheduler idle")

    t = threading.Thread(target=_run_scheduler, daemon=True)
    t.start()
    logger.info("Scheduler thread started")


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
def handle_shutdown(signum, frame):
    logger.info("Received signal %s — shutting down", signum)
    shutdown_executor()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    register_handlers()
    start_scheduler()

    # Run vault + journal indexers on startup
    try:
        from core.vault_indexer import run_full_index as index_vault
        from core.journal_indexer import run_full_index as index_journal
        vault_count = index_vault()
        journal_count = index_journal()
        logger.info("Startup index: %d vault files, %d journal entries", vault_count, journal_count)
    except Exception:
        logger.warning("Startup indexing failed — will work without cached index")

    logger.info("Starting Second Brain bot in Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()

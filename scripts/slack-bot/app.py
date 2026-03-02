"""Second Brain Slack Bot — Entry Point.

Bolt + Socket Mode app that bridges Slack with the Second Brain vault,
SQLite database, and Anthropic API.
"""
import logging
import signal
import sys
import threading

import schedule
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import (
    OWNER_SLACK_ID,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
def register_handlers():
    """Import and register all handler modules."""
    try:
        from handlers import register_all
        register_all(app)
        logger.info("All handlers registered")
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
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    register_handlers()
    start_scheduler()

    logger.info("Starting Second Brain bot in Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()

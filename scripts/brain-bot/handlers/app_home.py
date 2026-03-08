"""Slack App Home tab event handler and quick-action button handlers."""

import logging
import time

from slack_bolt import App

from core.app_home_builder import build_app_home_view
from core.async_utils import executor

logger = logging.getLogger(__name__)

# Cache: user_id -> (timestamp, view_payload)
_view_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60  # seconds


def _get_cached_view(user_id: str, db_path=None) -> dict:
    """Return cached view if fresh, otherwise rebuild and cache."""
    now = time.time()
    cached = _view_cache.get(user_id)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    view = build_app_home_view(user_id, db_path=db_path)
    _view_cache[user_id] = (now, view)
    return view


def register(app: App):
    """Register app_home_opened event and quick-action button handlers."""

    @app.event("app_home_opened")
    def handle_app_home_opened(event, client):
        user_id = event.get("user", "")
        try:
            view = _get_cached_view(user_id)
            client.views_publish(user_id=user_id, view=view)
        except Exception:
            logger.exception("Failed to publish App Home view for user %s", user_id)

    @app.action("app_home_morning_briefing")
    def handle_morning(ack, body, client):
        ack()
        user_id = body.get("user", {}).get("id", "")
        from handlers.commands import _run_ai_command
        executor.submit(_run_ai_command, client, user_id, "today", "brain-daily", "")

    @app.action("app_home_evening_review")
    def handle_evening(ack, body, client):
        ack()
        user_id = body.get("user", {}).get("id", "")
        from handlers.commands import _run_ai_command
        executor.submit(_run_ai_command, client, user_id, "close-day", "brain-daily", "")

    @app.action("app_home_search_vault")
    def handle_search(ack, body, client):
        ack()
        trigger_id = body.get("trigger_id", "")
        try:
            client.views_open(
                trigger_id=trigger_id,
                view={
                    "type": "modal",
                    "callback_id": "app_home_search_modal",
                    "title": {"type": "plain_text", "text": "Search Vault"},
                    "submit": {"type": "plain_text", "text": "Search"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "search_input_block",
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "search_query",
                                "placeholder": {"type": "plain_text", "text": "Enter search query..."},
                            },
                            "label": {"type": "plain_text", "text": "Query"},
                        }
                    ],
                },
            )
        except Exception:
            logger.exception("Failed to open search modal")

    @app.view("app_home_search_modal")
    def handle_search_submit(ack, body, client, view):
        ack()
        user_id = body.get("user", {}).get("id", "")
        values = view.get("state", {}).get("values", {})
        query = values.get("search_input_block", {}).get("search_query", {}).get("value", "")
        if query:
            from handlers.commands import _run_fast_search
            executor.submit(_run_fast_search, client, user_id, query)

    @app.action("app_home_sync_notion")
    def handle_sync(ack, body, client):
        ack()
        user_id = body.get("user", {}).get("id", "")
        from handlers.commands import _run_sync_command
        executor.submit(_run_sync_command, client, user_id, "")

    @app.action("app_home_weekly_review")
    def handle_review(ack, body, client):
        ack()
        user_id = body.get("user", {}).get("id", "")
        from handlers.commands import _run_ai_command
        executor.submit(_run_ai_command, client, user_id, "weekly-review", "brain-daily", "")

    @app.action("app_home_brain_status")
    def handle_status(ack, body, client):
        ack()
        user_id = body.get("user", {}).get("id", "")
        from handlers.commands import _run_status_command
        executor.submit(_run_status_command, client, user_id)

    # Handle Complete/Snooze buttons from pending actions on App Home
    @app.action("app_home_complete")
    def handle_complete_action(ack, body, client, action):
        ack()
        action_id = action.get("value", "")
        if not action_id:
            return
        try:
            from core.async_utils import run_async
            from core.db_ops import execute
            run_async(
                execute(
                    "UPDATE action_items SET status = 'completed', completed_at = datetime('now') WHERE id = ?",
                    (int(action_id),),
                )
            )
            # Refresh the App Home view
            user_id = body.get("user", {}).get("id", "")
            _view_cache.pop(user_id, None)
            view = _get_cached_view(user_id)
            client.views_publish(user_id=user_id, view=view)
        except Exception:
            logger.exception("Error completing action %s from App Home", action_id)

    @app.action("app_home_snooze")
    def handle_snooze_action(ack, body, client, action):
        ack()
        action_id = action.get("value", "")
        if not action_id:
            return
        try:
            from core.async_utils import run_async
            from core.db_ops import execute
            run_async(
                execute(
                    "UPDATE action_items SET source_date = date(source_date, '+1 day') WHERE id = ?",
                    (int(action_id),),
                )
            )
            # Refresh the App Home view
            user_id = body.get("user", {}).get("id", "")
            _view_cache.pop(user_id, None)
            view = _get_cached_view(user_id)
            client.views_publish(user_id=user_id, view=view)
        except Exception:
            logger.exception("Error snoozing action %s from App Home", action_id)

    @app.action("app_home_dismiss_alert")
    def handle_dismiss_alert(ack, body, client, action):
        ack()
        alert_id = action.get("value", "")
        if not alert_id:
            return
        try:
            from core.async_utils import run_async
            from core.db_ops import execute
            run_async(
                execute(
                    "UPDATE alerts SET status = 'dismissed', dismissed_at = datetime('now') WHERE id = ? AND status = 'active'",
                    (int(alert_id),),
                )
            )
            # Refresh the App Home view
            user_id = body.get("user", {}).get("id", "")
            _view_cache.pop(user_id, None)
            view = _get_cached_view(user_id)
            client.views_publish(user_id=user_id, view=view)
        except Exception:
            logger.exception("Error dismissing alert %s from App Home", alert_id)

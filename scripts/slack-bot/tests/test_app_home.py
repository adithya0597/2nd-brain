"""Tests for App Home tab builder and event handler."""

import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure slack-bot dir on path and config mock in place
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("aiosqlite", MagicMock())

from core.app_home_builder import (
    build_app_home_view,
    _build_dashboard_summary,
    _build_quick_actions,
    _build_recent_captures,
    _build_pending_actions,
    _relative_time,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_captures(db_path, captures):
    """Insert test captures into captures_log."""
    conn = sqlite3.connect(str(db_path))
    for text, dims, created_at in captures:
        conn.execute(
            "INSERT INTO captures_log (message_text, dimensions_json, created_at) VALUES (?, ?, ?)",
            (text, json.dumps(dims), created_at),
        )
    conn.commit()
    conn.close()


def _insert_actions(db_path, actions):
    """Insert test action items."""
    conn = sqlite3.connect(str(db_path))
    for desc, status, icor_element in actions:
        conn.execute(
            "INSERT INTO action_items (description, status, icor_element) VALUES (?, ?, ?)",
            (desc, status, icor_element),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests: build_app_home_view
# ---------------------------------------------------------------------------

class TestBuildAppHomeView:
    def test_returns_valid_block_kit_structure(self, test_db):
        view = build_app_home_view("U123", db_path=test_db)
        assert view["type"] == "home"
        assert isinstance(view["blocks"], list)
        assert len(view["blocks"]) > 0

    def test_contains_all_sections(self, test_db):
        view = build_app_home_view("U123", db_path=test_db)
        blocks = view["blocks"]
        # Should have header, sections, dividers, context
        block_types = [b["type"] for b in blocks]
        assert "header" in block_types
        assert "section" in block_types
        assert "divider" in block_types
        assert "actions" in block_types  # Quick action buttons


# ---------------------------------------------------------------------------
# Tests: Dashboard Summary
# ---------------------------------------------------------------------------

class TestDashboardSummary:
    def test_shows_six_icor_dimensions(self, test_db):
        blocks = _build_dashboard_summary(db_path=test_db)
        # Find the section block with the heatmap
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section"
        ]
        assert len(section_texts) > 0
        heatmap = section_texts[0]
        # All 6 short dimension names should appear
        for short_name in ["Health", "Wealth", "Relationships", "Mind", "Purpose", "Systems"]:
            assert short_name in heatmap

    def test_shows_pending_count(self, test_db):
        _insert_actions(test_db, [
            ("Task A", "pending", "Fitness"),
            ("Task B", "pending", None),
        ])
        blocks = _build_dashboard_summary(db_path=test_db)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section"
        ]
        heatmap = section_texts[0]
        assert "Pending: 2" in heatmap

    def test_shows_journaled_no_by_default(self, test_db):
        blocks = _build_dashboard_summary(db_path=test_db)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section"
        ]
        heatmap = section_texts[0]
        assert "Journaled: No" in heatmap


# ---------------------------------------------------------------------------
# Tests: Quick Actions
# ---------------------------------------------------------------------------

class TestQuickActions:
    def test_has_six_buttons(self):
        blocks = _build_quick_actions()
        buttons = []
        for b in blocks:
            if b.get("type") == "actions":
                buttons.extend(b.get("elements", []))
        assert len(buttons) == 6

    def test_button_action_ids(self):
        blocks = _build_quick_actions()
        action_ids = []
        for b in blocks:
            if b.get("type") == "actions":
                for elem in b.get("elements", []):
                    action_ids.append(elem.get("action_id"))
        expected = {
            "app_home_morning_briefing",
            "app_home_evening_review",
            "app_home_search_vault",
            "app_home_sync_notion",
            "app_home_weekly_review",
            "app_home_brain_status",
        }
        assert set(action_ids) == expected


# ---------------------------------------------------------------------------
# Tests: Recent Captures
# ---------------------------------------------------------------------------

class TestRecentCaptures:
    def test_handles_empty_captures_log(self, test_db):
        blocks = _build_recent_captures(db_path=test_db)
        # Implementation returns empty list when no captures exist
        assert blocks == []

    def test_shows_captures_grouped_by_dimension(self, test_db):
        _insert_captures(test_db, [
            ("Started running program", ["Health & Vitality"], "2026-03-07 10:00:00"),
            ("Read chapter 5 of Deep Work", ["Mind & Growth"], "2026-03-07 09:00:00"),
            ("Ate a healthy meal", ["Health & Vitality"], "2026-03-07 08:00:00"),
        ])
        blocks = _build_recent_captures(db_path=test_db)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section" and "RECENT" not in b["text"]["text"]
        ]
        # Should have sections for Health & Vitality and Mind & Growth
        all_text = "\n".join(section_texts)
        assert "Health & Vitality" in all_text
        assert "Mind & Growth" in all_text
        assert "running program" in all_text

    def test_limits_per_dimension(self, test_db):
        captures = [
            (f"Capture {i}", ["Health & Vitality"], f"2026-03-07 {10-i}:00:00")
            for i in range(5)
        ]
        _insert_captures(test_db, captures)
        blocks = _build_recent_captures(limit_per_dim=2, db_path=test_db)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section" and "Health & Vitality" in b["text"]["text"]
        ]
        # Should show at most 2 captures for Health & Vitality
        assert len(section_texts) == 1
        text = section_texts[0]
        # Count the bullet points (middle dot)
        assert text.count("\u00b7") <= 2


# ---------------------------------------------------------------------------
# Tests: Pending Actions
# ---------------------------------------------------------------------------

class TestPendingActions:
    def test_handles_empty_action_items(self, test_db):
        blocks = _build_pending_actions(db_path=test_db)
        # Implementation returns empty list when no pending actions
        assert blocks == []

    def test_shows_pending_actions(self, test_db):
        _insert_actions(test_db, [
            ("Submit quarterly review", "pending", "Purpose"),
            ("Buy groceries", "pending", "Health"),
            ("Done task", "completed", None),
        ])
        blocks = _build_pending_actions(db_path=test_db)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section" and "PENDING" not in b["text"]["text"]
        ]
        # Should show 2 pending actions (not the completed one)
        assert len(section_texts) == 2
        all_text = "\n".join(section_texts)
        assert "Submit quarterly review" in all_text
        assert "Buy groceries" in all_text
        assert "Done task" not in all_text

    def test_action_buttons_present(self, test_db):
        _insert_actions(test_db, [("Test task", "pending", None)])
        blocks = _build_pending_actions(db_path=test_db)
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) >= 1
        elements = action_blocks[0]["elements"]
        action_ids = [e["action_id"] for e in elements]
        assert "app_home_complete" in action_ids
        assert "app_home_snooze" in action_ids


# ---------------------------------------------------------------------------
# Tests: View Cache
# ---------------------------------------------------------------------------

class TestViewCache:
    def test_cache_hit_within_ttl(self, test_db):
        from handlers.app_home import _get_cached_view, _view_cache, _CACHE_TTL
        _view_cache.clear()

        # First call populates cache
        view1 = _get_cached_view("U_CACHE_TEST", db_path=test_db)
        assert "U_CACHE_TEST" in _view_cache

        # Second call should return cached (same object)
        view2 = _get_cached_view("U_CACHE_TEST", db_path=test_db)
        assert view1 is view2

    def test_cache_miss_expired_ttl(self, test_db):
        from handlers.app_home import _get_cached_view, _view_cache, _CACHE_TTL
        _view_cache.clear()

        # First call
        view1 = _get_cached_view("U_EXPIRE_TEST", db_path=test_db)
        assert "U_EXPIRE_TEST" in _view_cache

        # Manually expire the cache entry
        ts, payload = _view_cache["U_EXPIRE_TEST"]
        _view_cache["U_EXPIRE_TEST"] = (ts - _CACHE_TTL - 1, payload)

        # Next call should rebuild (different object)
        view2 = _get_cached_view("U_EXPIRE_TEST", db_path=test_db)
        assert view2 is not view1


# ---------------------------------------------------------------------------
# Tests: App Home Event Handler
# ---------------------------------------------------------------------------

class TestAppHomeEventHandler:
    def test_app_home_opened_calls_views_publish(self, test_db):
        from handlers.app_home import _view_cache
        _view_cache.clear()

        mock_app = MagicMock()
        registered_handlers = {}

        def capture_event(event_name):
            def decorator(func):
                registered_handlers[event_name] = func
                return func
            return decorator

        def capture_action(action_id):
            def decorator(func):
                registered_handlers[f"action:{action_id}"] = func
                return func
            return decorator

        def capture_view(callback_id):
            def decorator(func):
                registered_handlers[f"view:{callback_id}"] = func
                return func
            return decorator

        mock_app.event = capture_event
        mock_app.action = capture_action
        mock_app.view = capture_view

        from handlers.app_home import register
        register(mock_app)

        # Simulate app_home_opened event
        handler = registered_handlers["app_home_opened"]
        mock_client = MagicMock()

        with patch("handlers.app_home.build_app_home_view") as mock_build:
            mock_build.return_value = {"type": "home", "blocks": []}
            handler(
                event={"user": "U123"},
                client=mock_client,
            )

        mock_client.views_publish.assert_called_once()
        call_kwargs = mock_client.views_publish.call_args
        assert call_kwargs[1]["user_id"] == "U123"


# ---------------------------------------------------------------------------
# Tests: Relative Time Helper
# ---------------------------------------------------------------------------

class TestRelativeTime:
    def test_invalid_input(self):
        assert _relative_time("not-a-date") == "?"
        assert _relative_time(None) == "?"

    def test_recent_time(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        two_hours_ago = (now - timedelta(hours=2)).isoformat()
        result = _relative_time(two_hours_ago)
        assert result == "2h"

    def test_days_ago(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        three_days_ago = (now - timedelta(days=3)).isoformat()
        result = _relative_time(three_days_ago)
        assert result == "3d"

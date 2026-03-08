"""Tests for Telegram dashboard builder (replaces Slack app_home_builder)."""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure brain-bot dir on path and mock external deps
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("aiosqlite", MagicMock())

from core.dashboard_builder import (
    build_dashboard_view,
    _build_dashboard_summary,
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
# Tests: build_dashboard_view
# ---------------------------------------------------------------------------

class TestBuildDashboardView:
    def test_returns_html_and_keyboard(self, test_db):
        html, keyboard = build_dashboard_view(db_path=test_db)
        assert isinstance(html, str)
        assert len(html) > 0
        # keyboard is InlineKeyboardMarkup (mocked), just verify it was returned
        assert keyboard is not None

    def test_html_contains_dashboard_sections(self, test_db):
        html, _keyboard = build_dashboard_view(db_path=test_db)
        # Should contain the dashboard summary section
        assert "SECOND BRAIN DASHBOARD" in html
        # Should contain brain level section
        assert "BRAIN LEVEL" in html
        # Should contain engagement section
        assert "7-DAY ENGAGEMENT" in html
        # Should contain the updated timestamp
        assert "Updated:" in html


# ---------------------------------------------------------------------------
# Tests: Dashboard Summary
# ---------------------------------------------------------------------------

class TestDashboardSummary:
    def test_shows_six_icor_dimensions(self, test_db):
        html = _build_dashboard_summary(db_path=test_db)
        assert isinstance(html, str)
        # All 6 short dimension names should appear
        for short_name in ["Health", "Wealth", "Relationships", "Mind", "Purpose", "Systems"]:
            assert short_name in html

    def test_shows_pending_count(self, test_db):
        _insert_actions(test_db, [
            ("Task A", "pending", "Fitness"),
            ("Task B", "pending", None),
        ])
        html = _build_dashboard_summary(db_path=test_db)
        assert "Pending: 2" in html

    def test_shows_journaled_no_by_default(self, test_db):
        html = _build_dashboard_summary(db_path=test_db)
        assert "Journaled:" in html
        assert "No" in html

    def test_shows_journaled_yes_when_entry_exists(self, test_db):
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO journal_entries (date, content) VALUES (?, ?)",
            (today, "Today was a good day."),
        )
        conn.commit()
        conn.close()
        html = _build_dashboard_summary(db_path=test_db)
        assert "Journaled:" in html
        assert "Yes" in html

    def test_returns_string_not_list(self, test_db):
        result = _build_dashboard_summary(db_path=test_db)
        assert isinstance(result, str)
        # Must NOT be a list of dicts (old Block Kit format)
        assert not isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: Recent Captures
# ---------------------------------------------------------------------------

class TestRecentCaptures:
    def test_handles_empty_captures_log(self, test_db):
        result = _build_recent_captures(db_path=test_db)
        # Returns empty string when no captures exist
        assert result == ""

    def test_shows_captures_grouped_by_dimension(self, test_db):
        _insert_captures(test_db, [
            ("Started running program", ["Health & Vitality"], "2026-03-07 10:00:00"),
            ("Read chapter 5 of Deep Work", ["Mind & Growth"], "2026-03-07 09:00:00"),
            ("Ate a healthy meal", ["Health & Vitality"], "2026-03-07 08:00:00"),
        ])
        html = _build_recent_captures(db_path=test_db)
        assert isinstance(html, str)
        # Dimension names are HTML-escaped (& -> &amp;)
        assert "Health &amp; Vitality" in html
        assert "Mind &amp; Growth" in html
        assert "running program" in html

    def test_limits_per_dimension(self, test_db):
        captures = [
            (f"Capture {i}", ["Health & Vitality"], f"2026-03-07 {10-i:02d}:00:00")
            for i in range(5)
        ]
        _insert_captures(test_db, captures)
        html = _build_recent_captures(limit_per_dim=2, db_path=test_db)
        # Should show at most 2 captures for Health & Vitality (2 middle dots)
        assert html.count("\u00b7") <= 2

    def test_returns_string_not_list(self, test_db):
        _insert_captures(test_db, [
            ("Test capture", ["Health & Vitality"], "2026-03-07 10:00:00"),
        ])
        result = _build_recent_captures(db_path=test_db)
        assert isinstance(result, str)
        assert not isinstance(result, list)

    def test_contains_recent_captures_header(self, test_db):
        _insert_captures(test_db, [
            ("Some thought", ["Mind & Growth"], "2026-03-07 10:00:00"),
        ])
        html = _build_recent_captures(db_path=test_db)
        assert "RECENT CAPTURES" in html


# ---------------------------------------------------------------------------
# Tests: Pending Actions
# ---------------------------------------------------------------------------

class TestPendingActions:
    def test_handles_empty_action_items(self, test_db):
        html, keyboard_rows = _build_pending_actions(db_path=test_db)
        # Returns empty string and empty list when no pending actions
        assert html == ""
        assert keyboard_rows == []

    def test_shows_pending_actions(self, test_db):
        _insert_actions(test_db, [
            ("Submit quarterly review", "pending", "Purpose"),
            ("Buy groceries", "pending", "Health"),
            ("Done task", "completed", None),
        ])
        html, keyboard_rows = _build_pending_actions(db_path=test_db)
        assert isinstance(html, str)
        assert "Submit quarterly review" in html
        assert "Buy groceries" in html
        # Completed task should NOT appear
        assert "Done task" not in html

    def test_returns_keyboard_rows_for_pending(self, test_db):
        _insert_actions(test_db, [
            ("Test task 1", "pending", None),
            ("Test task 2", "pending", None),
        ])
        html, keyboard_rows = _build_pending_actions(db_path=test_db)
        assert isinstance(keyboard_rows, list)
        # Should have one row of buttons per pending action
        assert len(keyboard_rows) == 2
        # Each row should have 2 buttons (Complete + Snooze)
        for row in keyboard_rows:
            assert len(row) == 2

    def test_shows_icor_element_when_present(self, test_db):
        _insert_actions(test_db, [
            ("Morning jog", "pending", "Fitness"),
        ])
        html, _keyboard_rows = _build_pending_actions(db_path=test_db)
        assert "Morning jog" in html
        assert "Fitness" in html

    def test_pending_actions_header(self, test_db):
        _insert_actions(test_db, [("Task", "pending", None)])
        html, _keyboard_rows = _build_pending_actions(db_path=test_db)
        assert "PENDING ACTIONS" in html

    def test_returns_tuple_not_list(self, test_db):
        result = _build_pending_actions(db_path=test_db)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests: Relative Time Helper
# ---------------------------------------------------------------------------

class TestRelativeTime:
    def test_invalid_input(self):
        assert _relative_time("not-a-date") == "?"
        assert _relative_time(None) == "?"

    def test_recent_time(self):
        now = datetime.now()
        two_hours_ago = (now - timedelta(hours=2)).isoformat()
        result = _relative_time(two_hours_ago)
        assert result == "2h"

    def test_days_ago(self):
        now = datetime.now()
        three_days_ago = (now - timedelta(days=3)).isoformat()
        result = _relative_time(three_days_ago)
        assert result == "3d"

    def test_minutes_ago(self):
        now = datetime.now()
        thirty_min_ago = (now - timedelta(minutes=30)).isoformat()
        result = _relative_time(thirty_min_ago)
        assert result == "30m"

    def test_seconds_ago(self):
        now = datetime.now()
        ten_sec_ago = (now - timedelta(seconds=10)).isoformat()
        result = _relative_time(ten_sec_ago)
        assert result == "10s"

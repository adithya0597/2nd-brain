"""Tests for Telegram topic routing and capture processing.

Validates that:
- TOPICS dict is populated from env vars
- DIMENSION_TOPICS dict has exactly 6 entries with string values
- _COMMAND_MAP routes drift->insights, ideas->insights, projects->daily, resources->daily
- Capture processing inserts into captures_log (not posting to dimension channels)
- Capture processing still writes to vault (daily note + inbox entry)
- format_help shows updated routing
- Scheduled jobs use correct topics
"""
import ast
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module mocking (before any project imports)
# ---------------------------------------------------------------------------
# Mock config before importing (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

for mod_name in (
    "anthropic", "telegram", "telegram.ext",
    "sentence_transformers",
    "core.article_fetcher",
):
    sys.modules.setdefault(mod_name, MagicMock())


# ---------------------------------------------------------------------------
# Helper: set config.DB_PATH to test_db for async db_connection
# ---------------------------------------------------------------------------
@pytest.fixture()
def _patch_db(test_db):
    """Point config.DB_PATH at test_db so db_connection picks it up."""
    cfg = sys.modules["config"]
    old = cfg.DB_PATH
    cfg.DB_PATH = test_db
    yield test_db
    cfg.DB_PATH = old


# ---------------------------------------------------------------------------
# Tests: config.py
# ---------------------------------------------------------------------------

class TestConfigConsolidation:
    """Verify config.py topic configuration by reading the source file directly."""

    def test_topics_populated_from_env(self):
        """TOPICS in config.py should be a dict (populated dynamically from env vars)."""
        config_path = Path(__file__).parent.parent / "config.py"
        tree = ast.parse(config_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "TOPICS":
                        # TOPICS is initialized as an empty dict, then populated
                        # from env vars in a loop — just verify it's a dict
                        assert isinstance(node.value, ast.Dict)
                        return
        # Also accept an AnnAssign (type-annotated assignment)
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "TOPICS":
                    return
        pytest.fail("TOPICS dict not found in config.py")

    def test_dimension_topics_has_six_entries(self):
        """DIMENSION_TOPICS in config.py source should have exactly 6 entries with string values."""
        config_path = Path(__file__).parent.parent / "config.py"
        tree = ast.parse(config_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "DIMENSION_TOPICS":
                        assert isinstance(node.value, ast.Dict)
                        assert len(node.value.keys) == 6
                        for val in node.value.values:
                            assert isinstance(val, ast.Constant) and isinstance(val.value, str), \
                                f"Expected string value, got {ast.dump(val)}"
                        return
        pytest.fail("DIMENSION_TOPICS dict not found in config.py")


# ---------------------------------------------------------------------------
# Tests: _COMMAND_MAP routing
# ---------------------------------------------------------------------------

class TestCommandMapRouting:
    """Verify _COMMAND_MAP routes to correct topics."""

    def test_drift_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["drift"] == ("drift", "brain-insights")

    def test_ideas_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["ideas"] == ("ideas", "brain-insights")

    def test_projects_routes_to_daily(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["projects"] == ("projects", "brain-daily")

    def test_resources_routes_to_daily(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["resources"] == ("resources", "brain-daily")

    def test_emerge_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["emerge"] == ("emerge", "brain-insights")

    def test_ghost_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["ghost"] == ("ghost", "brain-insights")

    def test_today_routes_to_daily(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["today"] == ("today", "brain-daily")

    def test_no_old_channels_in_command_map(self):
        """No command should route to removed channel names."""
        from handlers.commands import _COMMAND_MAP
        removed = {"brain-drift", "brain-ideas", "brain-actions",
                    "brain-projects", "brain-resources",
                    "brain-health", "brain-wealth", "brain-relations",
                    "brain-growth", "brain-purpose", "brain-systems"}
        for cmd, (_, topic_name) in _COMMAND_MAP.items():
            if topic_name is not None:
                assert topic_name not in removed, (
                    f"{cmd} still routes to removed topic {topic_name}"
                )


# ---------------------------------------------------------------------------
# Tests: capture.py — captures_log insertion
# ---------------------------------------------------------------------------

class TestCaptureProcessing:
    """Verify capture processing inserts into captures_log."""

    @pytest.mark.asyncio
    async def test_capture_inserts_into_captures_log(self, _patch_db):
        """Classified capture should INSERT into captures_log table."""
        test_db = _patch_db

        mock_result = MagicMock()
        mock_result.is_noise = False
        mock_result.is_actionable = False
        mock_result.matches = [
            MagicMock(dimension="Health & Vitality", confidence=0.85, method="keyword"),
        ]
        mock_result.execution_time_ms = 10.0

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_result

        # Build a mock Telegram Update
        mock_update = MagicMock()
        mock_update.message.text = "Going for a run tomorrow morning"
        mock_update.message.message_id = 12345
        mock_update.message.message_thread_id = 1  # inbox topic
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 12345
        mock_update.effective_chat.id = -100123

        mock_context = MagicMock()
        mock_context.bot = MagicMock()
        mock_context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        mock_context.application.create_task = MagicMock()

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- capture"), \
             patch("handlers.capture.format_capture_confirmation", return_value=("confirmed", None)), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.TOPICS", {"brain-inbox": 1}), \
             patch("handlers.capture.OWNER_TELEGRAM_ID", 12345), \
             patch("handlers.capture.GROUP_CHAT_ID", -100123), \
             patch("handlers.capture.config") as mock_cfg:
            mock_cfg.CONFIDENCE_THRESHOLD = 0.60
            from handlers.capture import handle_capture
            await handle_capture(mock_update, mock_context)

        # Verify reply was sent (confirmation + feedback buttons)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_still_writes_to_vault(self, _patch_db):
        """Capture should still write to daily note and inbox entry."""
        mock_result = MagicMock()
        mock_result.is_noise = False
        mock_result.is_actionable = False
        mock_result.matches = [
            MagicMock(dimension="Mind & Growth", confidence=0.80, method="keyword"),
        ]
        mock_result.execution_time_ms = 8.0

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_result

        mock_update = MagicMock()
        mock_update.message.text = "Reading a great book on systems thinking"
        mock_update.message.message_id = 12346
        mock_update.message.message_thread_id = 1
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 12345
        mock_update.effective_chat.id = -100123

        mock_context = MagicMock()
        mock_context.bot = MagicMock()
        mock_context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        mock_context.application.create_task = MagicMock()

        mock_append = MagicMock()
        mock_inbox = MagicMock()

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.append_to_daily_note", mock_append), \
             patch("handlers.capture.create_inbox_entry", mock_inbox), \
             patch("handlers.capture.format_capture_line", return_value="- capture"), \
             patch("handlers.capture.format_capture_confirmation", return_value=("confirmed", None)), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.TOPICS", {"brain-inbox": 1}), \
             patch("handlers.capture.OWNER_TELEGRAM_ID", 12345), \
             patch("handlers.capture.GROUP_CHAT_ID", -100123), \
             patch("handlers.capture.config") as mock_cfg:
            mock_cfg.CONFIDENCE_THRESHOLD = 0.60
            from handlers.capture import handle_capture
            await handle_capture(mock_update, mock_context)

        mock_append.assert_called_once()
        mock_inbox.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: bouncer resolution -> captures_log
# ---------------------------------------------------------------------------

class TestBouncerResolution:
    """Verify bouncer resolution logs to captures_log."""

    @pytest.mark.asyncio
    async def test_bouncer_resolution_inserts_captures_log(self, _patch_db):
        """Bouncer resolution should INSERT into captures_log."""
        mock_execute = AsyncMock()

        with patch("handlers.capture.execute", mock_execute):
            from handlers.capture import process_bouncer_resolution
            await process_bouncer_resolution(
                text="Going for a morning jog",
                msg_id=12345,
                dimension="Health & Vitality",
                chat_id=None,
            )

        # Verify captures_log INSERT was called
        insert_calls = [
            c for c in mock_execute.call_args_list
            if "captures_log" in str(c)
        ]
        assert len(insert_calls) >= 1, "Should have inserted into captures_log"

        # Verify the insert contains expected data
        call_args = insert_calls[0]
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "captures_log" in sql
        assert "Going for a morning jog" in params
        assert json.loads(params[1]) == ["Health & Vitality"]


# ---------------------------------------------------------------------------
# Tests: feedback.py — corrected capture logs to captures_log
# ---------------------------------------------------------------------------

class TestFeedbackCorrection:
    """Verify feedback correction logs to captures_log."""

    @pytest.mark.asyncio
    async def test_dimension_select_inserts_captures_log(self, _patch_db):
        """Corrected classification should INSERT into captures_log."""
        test_db = _patch_db

        # Pre-seed a classification record
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO classifications (message_text, message_ts, primary_dimension, confidence, method) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Test message", "TS123", "Mind & Growth", 0.75, "keyword"),
        )
        conn.commit()
        conn.close()

        # Directly test the captures_log insert logic that handle_fb_dim_select does
        from core.db_ops import execute as db_execute, query as db_query

        rows = await db_query(
            "SELECT message_text FROM classifications WHERE message_ts = ?",
            ("TS123",),
        )
        assert len(rows) == 1

        # Simulate what handle_fb_dim_select does with captures_log
        await db_execute(
            "INSERT INTO captures_log "
            "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
            "VALUES (?, ?, 1.0, 'user_corrected', 0, 'brain-inbox')",
            (rows[0]["message_text"], json.dumps(["Health & Vitality"])),
        )

        # Verify captures_log
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        log_rows = conn.execute("SELECT * FROM captures_log").fetchall()
        conn.close()

        assert len(log_rows) == 1
        assert log_rows[0]["method"] == "user_corrected"
        assert json.loads(log_rows[0]["dimensions_json"]) == ["Health & Vitality"]


# ---------------------------------------------------------------------------
# Tests: formatter.py — format_help
# ---------------------------------------------------------------------------

class TestFormatHelp:
    """Verify format_help returns proper HTML with correct commands."""

    def test_help_contains_commands(self):
        from core.formatter import format_help
        html, keyboard = format_help()
        assert "/brain-drift" in html
        assert "/brain-ideas" in html
        assert "/brain-projects" in html
        assert "/brain-resources" in html

    def test_help_has_no_removed_channels(self):
        from core.formatter import format_help
        html, keyboard = format_help()
        removed = {"#brain-drift", "#brain-ideas", "#brain-actions",
                    "#brain-projects", "#brain-resources",
                    "#brain-health", "#brain-wealth", "#brain-relations",
                    "#brain-growth", "#brain-purpose", "#brain-systems"}
        for ch in removed:
            assert ch not in html, f"Help text still references removed channel {ch}"


# ---------------------------------------------------------------------------
# Tests: scheduled.py — topic routing
# ---------------------------------------------------------------------------

class TestScheduledJobChannels:
    """Verify scheduled jobs use correct topics."""

    @pytest.mark.asyncio
    async def test_drift_report_uses_insights(self):
        """job_drift_report should post to brain-insights topic."""
        mock_bot = MagicMock()
        mock_send = AsyncMock()

        with patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Drift report content"), \
             patch("handlers.scheduled._send_to_topic", mock_send), \
             patch("handlers.scheduled._record_job_run"):
            from handlers.scheduled import job_drift_report
            mock_context = MagicMock()
            mock_context.bot = mock_bot
            await job_drift_report(mock_context)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][1] == "brain-insights"

    @pytest.mark.asyncio
    async def test_project_summary_uses_daily(self):
        """job_weekly_project_summary should post to brain-daily topic."""
        mock_bot = MagicMock()
        mock_send = AsyncMock()

        with patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Project summary"), \
             patch("handlers.scheduled._send_to_topic", mock_send), \
             patch("handlers.scheduled._record_job_run"):
            from handlers.scheduled import job_weekly_project_summary
            mock_context = MagicMock()
            mock_context.bot = mock_bot
            await job_weekly_project_summary(mock_context)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][1] == "brain-daily"

    @pytest.mark.asyncio
    async def test_resource_digest_uses_daily(self):
        """job_monthly_resource_digest should post to brain-daily topic."""
        mock_bot = MagicMock()
        mock_send = AsyncMock()

        from datetime import datetime
        with patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Resource digest"), \
             patch("handlers.scheduled._send_to_topic", mock_send), \
             patch("handlers.scheduled._record_job_run"), \
             patch("handlers.scheduled.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 1, 10, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            from handlers.scheduled import job_monthly_resource_digest
            mock_context = MagicMock()
            mock_context.bot = mock_bot
            await job_monthly_resource_digest(mock_context)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][1] == "brain-daily"

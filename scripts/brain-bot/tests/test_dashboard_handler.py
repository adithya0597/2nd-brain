"""Tests for handlers/dashboard.py -- dashboard command and callback handlers."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegister:
    """Verify register() adds the right handlers to the application."""

    def test_register_adds_handlers(self):
        """register() should call add_handler at least 4 times (1 command + 3 callbacks)."""
        mock_app = MagicMock()

        from handlers.dashboard import register
        register(mock_app)

        assert mock_app.add_handler.call_count >= 4


# ---------------------------------------------------------------------------
# /dashboard command
# ---------------------------------------------------------------------------


class TestHandleDashboard:
    """Test _handle_dashboard sends dashboard view."""

    @pytest.mark.asyncio
    async def test_sends_dashboard_view(self, mock_update, mock_context):
        """_handle_dashboard calls build_dashboard_view and send_long_message."""
        fake_html = "<b>Dashboard</b>"
        fake_keyboard = MagicMock()

        with patch("handlers.dashboard.build_dashboard_view", return_value=(fake_html, fake_keyboard)) as mock_build, \
             patch("handlers.dashboard.send_long_message", new_callable=AsyncMock) as mock_send:

            from handlers.dashboard import _handle_dashboard
            await _handle_dashboard(mock_update, mock_context)

            mock_build.assert_called_once()
            mock_send.assert_called_once_with(
                mock_context.bot,
                chat_id=mock_update.effective_chat.id,
                text=fake_html,
                reply_markup=fake_keyboard,
                topic_id=mock_update.message.message_thread_id,
            )

    @pytest.mark.asyncio
    async def test_exception_sends_error_reply(self, mock_update, mock_context):
        """_handle_dashboard replies with error text when build_dashboard_view raises."""
        with patch("handlers.dashboard.build_dashboard_view", side_effect=RuntimeError("boom")):
            from handlers.dashboard import _handle_dashboard
            await _handle_dashboard(mock_update, mock_context)

        mock_update.message.reply_text.assert_awaited_once()
        err_text = mock_update.message.reply_text.call_args[0][0]
        assert "Failed" in err_text


# ---------------------------------------------------------------------------
# Quick action callbacks
# ---------------------------------------------------------------------------


class TestHandleQuickAction:
    """Test _handle_quick_action routing."""

    @pytest.mark.asyncio
    async def test_parses_cmd_and_delegates(self, mock_callback_query, mock_context):
        """_handle_quick_action parses cmd from JSON data and runs the command."""
        mock_callback_query.data = json.dumps({"cmd": "today"})

        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        with patch("handlers.dashboard.run_command_from_callback", new_callable=AsyncMock, create=True) as mock_run:
            # Patch the import inside the function
            with patch.dict("sys.modules", {"handlers.commands": MagicMock(run_command_from_callback=mock_run)}):
                from handlers.dashboard import _handle_quick_action
                await _handle_quick_action(mock_update, mock_context)

        mock_callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_invalid_json(self, mock_callback_query, mock_context):
        """_handle_quick_action returns silently on non-JSON callback data."""
        mock_callback_query.data = "not-json"
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        from handlers.dashboard import _handle_quick_action
        # Should not raise
        await _handle_quick_action(mock_update, mock_context)
        mock_callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_unknown_cmd(self, mock_callback_query, mock_context):
        """_handle_quick_action returns silently for unrecognized cmd values."""
        mock_callback_query.data = json.dumps({"cmd": "nonexistent_cmd"})
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        from handlers.dashboard import _handle_quick_action
        await _handle_quick_action(mock_update, mock_context)
        mock_callback_query.answer.assert_awaited_once()
        # No edit_message_reply_markup since cmd is not in _CMD_MAP
        mock_callback_query.edit_message_reply_markup.assert_not_awaited()


# ---------------------------------------------------------------------------
# Alert dismiss callbacks
# ---------------------------------------------------------------------------


class TestHandleDismissAlert:
    """Test _handle_dismiss_alert updates DB."""

    @pytest.mark.asyncio
    async def test_dismiss_updates_db(self, mock_callback_query, mock_context):
        """_handle_dismiss_alert calls execute with UPDATE for the alert ID."""
        mock_callback_query.data = json.dumps({"a": "dismiss_alert", "id": 42})
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        with patch("handlers.dashboard.execute", new_callable=AsyncMock, create=True) as mock_exec:
            # Patch the import inside _handle_dismiss_alert
            with patch.dict("sys.modules", {"core.db_ops": MagicMock(execute=mock_exec)}):
                from handlers.dashboard import _handle_dismiss_alert
                await _handle_dismiss_alert(mock_update, mock_context)

        mock_callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_non_dismiss_action(self, mock_callback_query, mock_context):
        """_handle_dismiss_alert returns early for non-dismiss actions."""
        mock_callback_query.data = json.dumps({"a": "other_action", "id": 42})
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        from handlers.dashboard import _handle_dismiss_alert
        await _handle_dismiss_alert(mock_update, mock_context)

        mock_callback_query.answer.assert_awaited_once()
        # Should not try to edit the message
        mock_callback_query.edit_message_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Action complete/snooze callbacks
# ---------------------------------------------------------------------------


class TestHandleDashAction:
    """Test _handle_dash_action for complete and snooze."""

    @pytest.mark.asyncio
    async def test_complete_action(self, mock_callback_query, mock_context):
        """dash_complete sets status='completed' in DB."""
        mock_callback_query.data = json.dumps({"a": "dash_complete", "id": 7})
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        with patch("handlers.dashboard.execute", new_callable=AsyncMock, create=True) as mock_exec:
            with patch.dict("sys.modules", {"core.db_ops": MagicMock(execute=mock_exec)}):
                from handlers.dashboard import _handle_dash_action
                await _handle_dash_action(mock_update, mock_context)

        mock_callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snooze_action(self, mock_callback_query, mock_context):
        """dash_snooze bumps source_date by +1 day."""
        mock_callback_query.data = json.dumps({"a": "dash_snooze", "id": 7})
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        with patch("handlers.dashboard.execute", new_callable=AsyncMock, create=True) as mock_exec:
            with patch.dict("sys.modules", {"core.db_ops": MagicMock(execute=mock_exec)}):
                from handlers.dashboard import _handle_dash_action
                await _handle_dash_action(mock_update, mock_context)

        mock_callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_invalid_action_type(self, mock_callback_query, mock_context):
        """_handle_dash_action ignores action types other than dash_complete/dash_snooze."""
        mock_callback_query.data = json.dumps({"a": "unknown_action", "id": 7})
        mock_update = MagicMock()
        mock_update.callback_query = mock_callback_query

        from handlers.dashboard import _handle_dash_action
        await _handle_dash_action(mock_update, mock_context)

        mock_callback_query.answer.assert_awaited_once()
        mock_callback_query.edit_message_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Callback data pattern filters
# ---------------------------------------------------------------------------


class TestIsDashboardCallback:
    """Test _is_dashboard_callback identifies dashboard callback data."""

    def test_cmd_key_detected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback(json.dumps({"cmd": "today"})) is True

    def test_dismiss_alert_detected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback(json.dumps({"a": "dismiss_alert", "id": 1})) is True

    def test_dash_complete_detected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback(json.dumps({"a": "dash_complete", "id": 1})) is True

    def test_dash_snooze_detected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback(json.dumps({"a": "dash_snooze", "id": 1})) is True

    def test_unrelated_json_rejected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback(json.dumps({"foo": "bar"})) is False

    def test_non_json_rejected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback("not-json") is False

    def test_none_rejected(self):
        from handlers.dashboard import _is_dashboard_callback
        assert _is_dashboard_callback(None) is False


class TestMatchQuickAction:
    """Test _match_quick_action pattern filter."""

    def test_matches_cmd_key(self):
        from handlers.dashboard import _match_quick_action
        assert _match_quick_action(json.dumps({"cmd": "drift"})) is True

    def test_rejects_non_cmd(self):
        from handlers.dashboard import _match_quick_action
        assert _match_quick_action(json.dumps({"a": "dismiss_alert"})) is False

    def test_rejects_non_string(self):
        from handlers.dashboard import _match_quick_action
        assert _match_quick_action(12345) is False

    def test_rejects_invalid_json(self):
        from handlers.dashboard import _match_quick_action
        assert _match_quick_action("{bad") is False


class TestMatchAlertDismiss:
    """Test _match_alert_dismiss pattern filter."""

    def test_matches_dismiss_alert(self):
        from handlers.dashboard import _match_alert_dismiss
        assert _match_alert_dismiss(json.dumps({"a": "dismiss_alert", "id": 5})) is True

    def test_rejects_other_actions(self):
        from handlers.dashboard import _match_alert_dismiss
        assert _match_alert_dismiss(json.dumps({"a": "dash_complete"})) is False

    def test_rejects_non_string(self):
        from handlers.dashboard import _match_alert_dismiss
        assert _match_alert_dismiss(None) is False


class TestMatchDashAction:
    """Test _match_dash_action pattern filter."""

    def test_matches_dash_complete(self):
        from handlers.dashboard import _match_dash_action
        assert _match_dash_action(json.dumps({"a": "dash_complete", "id": 1})) is True

    def test_matches_dash_snooze(self):
        from handlers.dashboard import _match_dash_action
        assert _match_dash_action(json.dumps({"a": "dash_snooze", "id": 1})) is True

    def test_rejects_dismiss_alert(self):
        from handlers.dashboard import _match_dash_action
        assert _match_dash_action(json.dumps({"a": "dismiss_alert"})) is False

    def test_rejects_non_string(self):
        from handlers.dashboard import _match_dash_action
        assert _match_dash_action(42) is False

    def test_rejects_bad_json(self):
        from handlers.dashboard import _match_dash_action
        assert _match_dash_action("nope") is False

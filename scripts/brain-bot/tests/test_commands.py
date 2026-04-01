"""Tests for handlers/commands.py — command handler logic."""
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

cfg = sys.modules["config"]
cfg.DB_PATH = Path("/tmp/test.db")
cfg.VAULT_PATH = Path("/tmp/vault")
cfg.GROUP_CHAT_ID = -100123
cfg.OWNER_TELEGRAM_ID = 12345
cfg.TOPICS = {"brain-daily": 2, "brain-insights": 3, "brain-dashboard": 4}
cfg.NOTION_TOKEN = ""
cfg.NOTION_COLLECTIONS = {}
cfg.NOTION_REGISTRY_PATH = Path("/tmp/registry.json")

from handlers.commands import (
    _owner_only,
    _write_command_output_to_vault,
    _run_ai_command,
    _handle_status,
    _handle_sync,
    _handle_cost,
    _handle_find,
    _handle_help,
    register,
    _COMMAND_MAP,
    _AUTO_VAULT_WRITE_COMMANDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = -100123
    update.message.reply_text = AsyncMock(return_value=MagicMock(
        edit_text=AsyncMock(),
        delete=AsyncMock(),
        message_id=42,
    ))
    update.message.text = "/today"
    return update


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.args = []
    return ctx


# ---------------------------------------------------------------------------
# _owner_only
# ---------------------------------------------------------------------------

class TestOwnerOnly:
    def test_owner_allowed(self):
        update = MagicMock()
        update.effective_user.id = 12345
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            assert _owner_only(update) is True

    def test_non_owner_blocked(self):
        update = MagicMock()
        update.effective_user.id = 99999
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            assert _owner_only(update) is False

    def test_no_owner_configured(self):
        update = MagicMock()
        update.effective_user.id = 99999
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 0):
            assert _owner_only(update) is True

    def test_no_user(self):
        update = MagicMock()
        update.effective_user = None
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            assert _owner_only(update) is False


# ---------------------------------------------------------------------------
# _write_command_output_to_vault
# ---------------------------------------------------------------------------

class TestWriteCommandOutputToVault:
    def test_close_day(self):
        with (
            patch("handlers.commands.ensure_daily_note"),
            patch("handlers.commands.append_to_daily_note") as mock_append,
        ):
            _write_command_output_to_vault("close-day", "Evening summary", "")
        mock_append.assert_called_once()
        assert "Evening Review" in mock_append.call_args[0][1]

    def test_today(self):
        with (
            patch("handlers.commands.ensure_daily_note"),
            patch("handlers.commands.append_to_daily_note") as mock_append,
        ):
            _write_command_output_to_vault("today", "Morning plan", "")
        mock_append.assert_called_once()
        assert "Morning Plan" in mock_append.call_args[0][1]

    def test_schedule(self):
        with patch("handlers.commands.create_weekly_plan") as mock_plan:
            _write_command_output_to_vault("schedule", "Week plan", "")
        mock_plan.assert_called_once()

    def test_auto_vault_write(self):
        with patch("handlers.commands.create_report_file") as mock_report:
            _write_command_output_to_vault("drift", "Drift results", "")
        mock_report.assert_called_once_with("drift", "Drift results")

    def test_graduate(self):
        with patch("handlers.commands.create_report_file") as mock_report:
            _write_command_output_to_vault("graduate", "Graduate results", "")
        mock_report.assert_called_once()

    def test_error_does_not_raise(self):
        with patch("handlers.commands.ensure_daily_note", side_effect=Exception("disk full")):
            _write_command_output_to_vault("today", "Morning", "")


# ---------------------------------------------------------------------------
# _run_ai_command
# ---------------------------------------------------------------------------

class TestRunAiCommand:
    @pytest.mark.asyncio
    async def test_success_flow(self, mock_update, mock_context):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="AI result")]

        mock_ai = MagicMock()
        mock_ai.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch("handlers.commands.gather_command_context", new_callable=AsyncMock, return_value={}),
            patch("handlers.commands.load_system_context", return_value="system"),
            patch("handlers.commands.load_command_prompt", return_value="prompt"),
            patch("handlers.commands.build_claude_messages", return_value=[]),
            patch("handlers.commands.get_ai_client", return_value=mock_ai),
            patch("handlers.commands.get_ai_model", return_value="test-model"),
            patch("handlers.commands.run_in_executor", new_callable=AsyncMock),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock),
        ):
            await _run_ai_command(mock_update, mock_context, "today", "brain-daily")

    @pytest.mark.asyncio
    async def test_no_ai_client(self, mock_update, mock_context):
        with (
            patch("handlers.commands.gather_command_context", new_callable=AsyncMock, return_value={}),
            patch("handlers.commands.load_system_context", return_value="system"),
            patch("handlers.commands.load_command_prompt", return_value="prompt"),
            patch("handlers.commands.build_claude_messages", return_value=[]),
            patch("handlers.commands.get_ai_client", return_value=None),
            patch("handlers.commands.get_ai_model", return_value="test"),
        ):
            await _run_ai_command(mock_update, mock_context, "today", "brain-daily")
        # Should have edited the progress message with error
        msg = mock_update.message.reply_text.return_value
        msg.edit_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_error_flow(self, mock_update, mock_context):
        with (
            patch("handlers.commands.gather_command_context", new_callable=AsyncMock, side_effect=Exception("ctx fail")),
            patch("handlers.commands.format_error", return_value=("Error HTML", None)),
        ):
            await _run_ai_command(mock_update, mock_context, "today", "brain-daily")

    @pytest.mark.asyncio
    async def test_projects_gets_save_button(self, mock_update, mock_context):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Projects result")]

        mock_ai = MagicMock()
        mock_ai.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch("handlers.commands.gather_command_context", new_callable=AsyncMock, return_value={}),
            patch("handlers.commands.load_system_context", return_value="system"),
            patch("handlers.commands.load_command_prompt", return_value="prompt"),
            patch("handlers.commands.build_claude_messages", return_value=[]),
            patch("handlers.commands.get_ai_client", return_value=mock_ai),
            patch("handlers.commands.get_ai_model", return_value="test-model"),
            patch("handlers.commands.run_in_executor", new_callable=AsyncMock),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock) as mock_send,
        ):
            await _run_ai_command(mock_update, mock_context, "projects", "brain-daily")
        # Should have reply_markup for save button
        assert mock_send.call_args.kwargs.get("reply_markup") is not None


# ---------------------------------------------------------------------------
# _handle_status
# ---------------------------------------------------------------------------

class TestHandleStatus:
    @pytest.mark.asyncio
    async def test_success(self, mock_update, mock_context):
        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.get_pending_actions", new_callable=AsyncMock, return_value=[]),
            patch("handlers.commands.get_neglected_elements", new_callable=AsyncMock, return_value=[]),
            patch("handlers.commands.get_attention_scores", new_callable=AsyncMock, return_value=[]),
            patch("handlers.commands.get_recent_journal", new_callable=AsyncMock, return_value=[]),
            patch("handlers.commands.format_dashboard", return_value=("<b>Dashboard</b>", None)),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock),
        ):
            await _handle_status(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_non_owner_skips(self, mock_update, mock_context):
        mock_update.effective_user.id = 99999
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            await _handle_status(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_sync
# ---------------------------------------------------------------------------

class TestHandleSync:
    @pytest.mark.asyncio
    async def test_no_token(self, mock_update, mock_context):
        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.NOTION_TOKEN", ""),
        ):
            await _handle_sync(mock_update, mock_context)
        # Should reply with error about missing token
        mock_update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_sync_success(self, mock_update, mock_context):
        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.warnings = []

        mock_notion = MagicMock()
        mock_notion.close = AsyncMock()
        mock_syncer = MagicMock()
        mock_syncer.run_full_sync = AsyncMock(return_value=mock_result)

        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.NOTION_TOKEN", "test-token"),
            patch("handlers.commands.NotionClientWrapper", return_value=mock_notion),
            patch("handlers.commands.NotionSync", return_value=mock_syncer),
            patch("handlers.commands.format_sync_report", return_value=("<b>Sync OK</b>", None)),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock),
            patch("handlers.commands.get_ai_client", return_value=None),
            patch("handlers.commands.get_ai_model", return_value="test"),
        ):
            await _handle_sync(mock_update, mock_context)


# ---------------------------------------------------------------------------
# _handle_cost
# ---------------------------------------------------------------------------

class TestHandleCost:
    @pytest.mark.asyncio
    async def test_default_30_days(self, mock_update, mock_context):
        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.get_cost_summary", new_callable=AsyncMock, return_value={"daily": [], "by_caller": [], "by_model": []}),
            patch("handlers.commands.format_cost_report", return_value=("<b>Costs</b>", None)),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock),
        ):
            await _handle_cost(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_custom_days(self, mock_update, mock_context):
        mock_context.args = ["7"]
        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.get_cost_summary", new_callable=AsyncMock, return_value={"daily": [], "by_caller": [], "by_model": []}) as mock_cost,
            patch("handlers.commands.format_cost_report", return_value=("<b>Costs</b>", None)),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock),
        ):
            await _handle_cost(mock_update, mock_context)
        mock_cost.assert_awaited_once_with(7)


# ---------------------------------------------------------------------------
# _handle_find
# ---------------------------------------------------------------------------

class TestHandleFind:
    @pytest.mark.asyncio
    async def test_no_input(self, mock_update, mock_context):
        mock_context.args = []
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            await _handle_find(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        assert "Usage" in mock_update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_ai_flag_delegates(self, mock_update, mock_context):
        mock_context.args = ["--ai", "fitness"]
        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands._run_ai_command", new_callable=AsyncMock) as mock_ai,
        ):
            await _handle_find(mock_update, mock_context)
        mock_ai.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_with_results(self, mock_update, mock_context):
        mock_context.args = ["fitness"]

        mock_result = MagicMock()
        mock_result.results = [MagicMock(title="Fitness", file_path="f.md", snippet="...", sources=["fts"])]
        mock_result.channels_used = ["fts"]
        mock_result.total_candidates = 5

        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.run_in_executor", new_callable=AsyncMock, return_value=mock_result),
            patch("core.formatter.format_search_results", return_value=("<b>Results</b>", None)),
            patch("handlers.commands.send_long_message", new_callable=AsyncMock),
        ):
            await _handle_find(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_search_no_results(self, mock_update, mock_context):
        mock_context.args = ["nonexistent"]

        mock_result = MagicMock()
        mock_result.results = []

        with (
            patch("handlers.commands.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.commands.run_in_executor", new_callable=AsyncMock, return_value=mock_result),
        ):
            await _handle_find(mock_update, mock_context)


# ---------------------------------------------------------------------------
# _handle_help
# ---------------------------------------------------------------------------

class TestHandleHelp:
    @pytest.mark.asyncio
    async def test_returns_help(self, mock_update, mock_context):
        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            await _handle_help(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_registers_handlers(self):
        app = MagicMock()
        register(app)
        # At least the command map entries + special commands
        assert app.add_handler.call_count >= len(_COMMAND_MAP) + 5


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_command_map_has_today(self):
        assert "today" in _COMMAND_MAP

    def test_auto_vault_write_commands(self):
        assert "drift" in _AUTO_VAULT_WRITE_COMMANDS
        assert "ideas" in _AUTO_VAULT_WRITE_COMMANDS

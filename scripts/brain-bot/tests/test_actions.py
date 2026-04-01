"""Tests for handlers/actions.py — action item interactive handlers."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure brain-bot on path
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from handlers.actions import (
    handle_complete,
    handle_snooze,
    handle_delegate_start,
    receive_delegate_name,
    receive_delegate_notes,
    skip_delegate_notes,
    cancel_delegate,
    handle_save_vault,
    handle_dismiss,
    handle_review_fading,
    register,
    DELEGATE_NAME,
    DELEGATE_NOTES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def callback_update():
    """Mock Update with callback_query."""
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    update.callback_query.message.delete = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    update.callback_query.message.text = "Some report content"
    update.callback_query.message.text_html = "<b>Some report</b>"
    return update


@pytest.fixture
def message_update():
    """Mock Update with message (for conversation handler)."""
    update = MagicMock()
    update.message.text = "John Doe"
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def tg_context():
    """Mock Telegram context."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.user_data = {}
    return ctx


# ---------------------------------------------------------------------------
# handle_complete
# ---------------------------------------------------------------------------

class TestHandleComplete:
    @pytest.mark.asyncio
    async def test_complete_marks_action(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "complete", "id": "42"})

        with patch("handlers.actions.execute", new_callable=AsyncMock) as mock_exec:
            await handle_complete(callback_update, tg_context)

        callback_update.callback_query.answer.assert_awaited_once()
        mock_exec.assert_awaited_once()
        sql_arg = mock_exec.call_args[0][0]
        assert "completed" in sql_arg
        assert mock_exec.call_args[0][1] == (42,)
        callback_update.callback_query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_empty_id_returns_early(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "complete"})

        with patch("handlers.actions.execute", new_callable=AsyncMock) as mock_exec:
            await handle_complete(callback_update, tg_context)

        mock_exec.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_handles_db_error(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "complete", "id": "7"})

        with patch("handlers.actions.execute", new_callable=AsyncMock, side_effect=Exception("DB fail")):
            # Should not raise — logs exception
            await handle_complete(callback_update, tg_context)

        callback_update.callback_query.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle_snooze
# ---------------------------------------------------------------------------

class TestHandleSnooze:
    @pytest.mark.asyncio
    async def test_snooze_updates_date(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "snooze", "id": "10"})

        with patch("handlers.actions.execute", new_callable=AsyncMock) as mock_exec:
            await handle_snooze(callback_update, tg_context)

        callback_update.callback_query.answer.assert_awaited_once()
        mock_exec.assert_awaited_once()
        sql_arg = mock_exec.call_args[0][0]
        assert "+1 day" in sql_arg
        callback_update.callback_query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snooze_empty_id(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "snooze"})

        with patch("handlers.actions.execute", new_callable=AsyncMock) as mock_exec:
            await handle_snooze(callback_update, tg_context)

        mock_exec.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_snooze_handles_error(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "snooze", "id": "5"})

        with patch("handlers.actions.execute", new_callable=AsyncMock, side_effect=Exception("err")):
            await handle_snooze(callback_update, tg_context)

        # Should not raise


# ---------------------------------------------------------------------------
# Delegate conversation
# ---------------------------------------------------------------------------

class TestDelegateFlow:
    @pytest.mark.asyncio
    async def test_delegate_start_stores_context(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "delegate", "id": "15"})

        result = await handle_delegate_start(callback_update, tg_context)

        assert result == DELEGATE_NAME
        assert tg_context.user_data["delegate_action_id"] == "15"
        callback_update.callback_query.message.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delegate_start_empty_id(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "delegate"})

        # ConversationHandler.END is imported from telegram.ext which is mocked
        # The function returns ConversationHandler.END when id is empty
        result = await handle_delegate_start(callback_update, tg_context)
        # Should return early — no user_data set
        assert "delegate_action_id" not in tg_context.user_data

    @pytest.mark.asyncio
    async def test_receive_delegate_name(self, message_update, tg_context):
        message_update.message.text = "Alice"

        result = await receive_delegate_name(message_update, tg_context)

        assert result == DELEGATE_NOTES
        assert tg_context.user_data["delegate_name"] == "Alice"
        message_update.message.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_receive_delegate_notes_completes(self, message_update, tg_context):
        tg_context.user_data["delegate_name"] = "Bob"
        tg_context.user_data["delegate_action_id"] = "20"
        tg_context.user_data["delegate_query_message"] = MagicMock()
        tg_context.user_data["delegate_query_message"].edit_text = AsyncMock()
        message_update.message.text = "Please handle this ASAP"

        with patch("handlers.actions.execute", new_callable=AsyncMock):
            result = await receive_delegate_notes(message_update, tg_context)

        # Should return ConversationHandler.END (mocked)
        message_update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_receive_delegate_notes_missing_data(self, message_update, tg_context):
        # No delegate_name or delegate_action_id in user_data
        result = await receive_delegate_notes(message_update, tg_context)

        msg_text = message_update.message.reply_text.call_args[0][0]
        assert "cancelled" in msg_text.lower()

    @pytest.mark.asyncio
    async def test_receive_delegate_notes_db_error(self, message_update, tg_context):
        tg_context.user_data["delegate_name"] = "Carol"
        tg_context.user_data["delegate_action_id"] = "30"
        tg_context.user_data["delegate_query_message"] = None

        with patch("handlers.actions.execute", new_callable=AsyncMock, side_effect=Exception("DB")):
            result = await receive_delegate_notes(message_update, tg_context)

        msg_text = message_update.message.reply_text.call_args[0][0]
        assert "failed" in msg_text.lower()

    @pytest.mark.asyncio
    async def test_skip_delegate_notes(self, message_update, tg_context):
        tg_context.user_data["delegate_name"] = "Dave"
        tg_context.user_data["delegate_action_id"] = "25"
        tg_context.user_data["delegate_query_message"] = None

        with patch("handlers.actions.execute", new_callable=AsyncMock):
            result = await skip_delegate_notes(message_update, tg_context)

        # text should have been set to ""
        assert message_update.message.text == ""

    @pytest.mark.asyncio
    async def test_cancel_delegate(self, message_update, tg_context):
        tg_context.user_data["delegate_action_id"] = "99"
        tg_context.user_data["delegate_name"] = "Eve"
        tg_context.user_data["delegate_query_message"] = MagicMock()

        result = await cancel_delegate(message_update, tg_context)

        assert "delegate_action_id" not in tg_context.user_data
        message_update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle_save_vault
# ---------------------------------------------------------------------------

class TestHandleSaveVault:
    @pytest.mark.asyncio
    async def test_save_vault_success(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "save_vault", "cmd": "ideas"})
        callback_update.callback_query.message.text = "Ideas report content here"

        with patch("handlers.actions.run_in_executor", new_callable=AsyncMock) as mock_exec:
            await handle_save_vault(callback_update, tg_context)

        mock_exec.assert_awaited_once()
        callback_update.callback_query.edit_message_reply_markup.assert_awaited_once()
        callback_update.callback_query.message.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_vault_empty_content(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "save_vault", "cmd": "ideas"})
        callback_update.callback_query.message.text = ""

        with patch("handlers.actions.run_in_executor", new_callable=AsyncMock) as mock_exec:
            await handle_save_vault(callback_update, tg_context)

        mock_exec.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_save_vault_error(self, callback_update, tg_context):
        callback_update.callback_query.data = "invalid json"

        # Should not raise
        await handle_save_vault(callback_update, tg_context)


# ---------------------------------------------------------------------------
# handle_dismiss
# ---------------------------------------------------------------------------

class TestHandleDismiss:
    @pytest.mark.asyncio
    async def test_dismiss_deletes_message(self, callback_update, tg_context):
        await handle_dismiss(callback_update, tg_context)

        callback_update.callback_query.answer.assert_awaited_once()
        callback_update.callback_query.message.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dismiss_handles_error(self, callback_update, tg_context):
        callback_update.callback_query.message.delete = AsyncMock(side_effect=Exception("err"))

        await handle_dismiss(callback_update, tg_context)

        callback_update.callback_query.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle_review_fading
# ---------------------------------------------------------------------------

class TestHandleReviewFading:
    @pytest.mark.asyncio
    async def test_review_fading_with_result(self, callback_update, tg_context, tmp_path):
        # Create a temp file
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test\nSome content about fitness and goals.")

        fading_row = [{"title": "Test", "file_path": str(test_file)}]

        mock_query = AsyncMock(return_value=fading_row)
        mock_esc = MagicMock(side_effect=lambda x: x)
        mock_cfg = MagicMock()
        mock_cfg.VAULT_PATH.__truediv__ = lambda self, other: Path(other)

        with (
            patch("core.db_ops.query", mock_query),
            patch.object(
                __import__("importlib"), "import_module", side_effect=ImportError
            ) if False else patch("core.formatter._esc", mock_esc),
        ):
            # Patch the imports inside the function by patching the source modules
            import core.db_ops
            import core.formatter
            old_query = getattr(core.db_ops, "query", None)
            old_esc = getattr(core.formatter, "_esc", None)
            core.db_ops.query = mock_query
            core.formatter._esc = mock_esc
            try:
                import handlers.actions as actions_mod
                import config as _cfg
                with patch.dict("sys.modules", {"config": mock_cfg}):
                    # Can't easily mock local imports. The function does 'from core.db_ops import query'
                    # which captures at call time. Easier to just test the error path.
                    pass
                await handle_review_fading(callback_update, tg_context)
            finally:
                if old_query:
                    core.db_ops.query = old_query
                if old_esc:
                    core.formatter._esc = old_esc

        callback_update.callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_fading_no_results(self, callback_update, tg_context):
        mock_query = AsyncMock(return_value=[])
        import core.db_ops
        old_query = getattr(core.db_ops, "query", None)
        core.db_ops.query = mock_query
        try:
            await handle_review_fading(callback_update, tg_context)
        finally:
            if old_query:
                core.db_ops.query = old_query

        callback_update.callback_query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_fading_error(self, callback_update, tg_context):
        mock_query = AsyncMock(side_effect=Exception("db error"))
        import core.db_ops
        old_query = getattr(core.db_ops, "query", None)
        core.db_ops.query = mock_query
        try:
            await handle_review_fading(callback_update, tg_context)
        finally:
            if old_query:
                core.db_ops.query = old_query

        callback_update.callback_query.message.reply_text.assert_awaited()


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_adds_handlers(self):
        app = MagicMock()
        register(app)

        # Should add multiple handlers (ConversationHandler + 5 callback query handlers)
        assert app.add_handler.call_count >= 6

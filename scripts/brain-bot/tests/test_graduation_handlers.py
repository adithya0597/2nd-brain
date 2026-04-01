"""Tests for handlers/graduation.py — graduation proposal handlers."""
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

cfg = sys.modules["config"]
cfg.VAULT_PATH = Path("/tmp/vault")

from handlers.graduation import (
    format_graduation_proposal,
    _graduate_proposal,
    handle_gc_approve,
    handle_gc_reject,
    handle_gc_snooze,
    handle_gc_edit_start,
    receive_gc_name,
    cancel_gc_edit,
    register,
    GC_EDIT_NAME,
)


@pytest.fixture
def sample_proposal():
    return {
        "id": 42,
        "proposed_title": "Mindfulness Practice",
        "proposed_dimension": "Mind & Growth",
        "capture_count": 5,
        "days_span": 14,
        "source_texts": json.dumps(["Morning meditation was great", "Tried breathing exercises"]),
        "source_capture_ids": json.dumps([1, 2, 3, 4, 5]),
    }


@pytest.fixture
def callback_update():
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def message_update():
    update = MagicMock()
    update.message.text = "New Concept Name"
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def tg_context():
    ctx = MagicMock()
    ctx.user_data = {}
    return ctx


# ---------------------------------------------------------------------------
# format_graduation_proposal
# ---------------------------------------------------------------------------

class TestFormatGraduationProposal:
    def test_basic(self, sample_proposal):
        text, kb = format_graduation_proposal(sample_proposal)
        assert "Mindfulness Practice" in text
        assert "Mind &amp; Growth" in text
        assert "5 captures" in text
        assert "14 days" in text
        assert "Morning meditation" in text
        assert kb is not None

    def test_minimal_proposal(self):
        proposal = {
            "id": 1,
            "proposed_title": "Test",
            "proposed_dimension": "",
            "capture_count": 0,
            "days_span": 0,
            "source_texts": "[]",
        }
        text, kb = format_graduation_proposal(proposal)
        assert "Test" in text
        assert kb is not None

    def test_long_source_texts(self):
        long_text = "x" * 200
        proposal = {
            "id": 1,
            "proposed_title": "Long",
            "proposed_dimension": "Health",
            "capture_count": 1,
            "days_span": 1,
            "source_texts": json.dumps([long_text]),
        }
        text, _ = format_graduation_proposal(proposal)
        assert "..." in text  # truncated


# ---------------------------------------------------------------------------
# _graduate_proposal
# ---------------------------------------------------------------------------

class TestGraduateProposal:
    @pytest.mark.asyncio
    async def test_success(self, sample_proposal, tmp_path):
        mock_path = tmp_path / "Concepts" / "Mindfulness-Practice.md"
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        mock_path.write_text("# Test")

        with (
            patch("handlers.graduation.create_concept_file", return_value=mock_path),
            patch("handlers.graduation.insert_concept_metadata", new_callable=AsyncMock),
            patch("handlers.graduation.execute", new_callable=AsyncMock),
            patch("handlers.graduation.config") as mock_cfg,
        ):
            mock_cfg.VAULT_PATH = tmp_path
            result = await _graduate_proposal(sample_proposal, "Mindfulness Practice")

        assert "Mindfulness-Practice.md" in result


# ---------------------------------------------------------------------------
# handle_gc_approve
# ---------------------------------------------------------------------------

class TestHandleGcApprove:
    @pytest.mark.asyncio
    async def test_approve_success(self, callback_update, tg_context, sample_proposal, tmp_path):
        callback_update.callback_query.data = json.dumps({"a": "gc_approve", "p": 42})

        mock_path = tmp_path / "Concepts" / "Mindfulness-Practice.md"
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        mock_path.write_text("# Test")

        with (
            patch("handlers.graduation.query", new_callable=AsyncMock, return_value=[sample_proposal]),
            patch("handlers.graduation._graduate_proposal", new_callable=AsyncMock, return_value="Concepts/Mindfulness-Practice.md"),
        ):
            await handle_gc_approve(callback_update, tg_context)

        callback_update.callback_query.edit_message_text.assert_awaited_once()
        text = callback_update.callback_query.edit_message_text.call_args[0][0]
        assert "Graduated" in text

    @pytest.mark.asyncio
    async def test_approve_not_found(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "gc_approve", "p": 999})

        with patch("handlers.graduation.query", new_callable=AsyncMock, return_value=[]):
            await handle_gc_approve(callback_update, tg_context)

        text = callback_update.callback_query.edit_message_text.call_args[0][0]
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_approve_failure(self, callback_update, tg_context, sample_proposal):
        callback_update.callback_query.data = json.dumps({"a": "gc_approve", "p": 42})

        with (
            patch("handlers.graduation.query", new_callable=AsyncMock, return_value=[sample_proposal]),
            patch("handlers.graduation._graduate_proposal", new_callable=AsyncMock, side_effect=Exception("fail")),
        ):
            await handle_gc_approve(callback_update, tg_context)

        text = callback_update.callback_query.edit_message_text.call_args[0][0]
        assert "Failed" in text


# ---------------------------------------------------------------------------
# handle_gc_reject
# ---------------------------------------------------------------------------

class TestHandleGcReject:
    @pytest.mark.asyncio
    async def test_reject(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "gc_reject", "p": 42})

        with (
            patch("handlers.graduation.execute", new_callable=AsyncMock),
            patch("handlers.graduation.query", new_callable=AsyncMock, return_value=[{"proposed_title": "Test Concept"}]),
        ):
            await handle_gc_reject(callback_update, tg_context)

        text = callback_update.callback_query.edit_message_text.call_args[0][0]
        assert "Rejected" in text


# ---------------------------------------------------------------------------
# handle_gc_snooze
# ---------------------------------------------------------------------------

class TestHandleGcSnooze:
    @pytest.mark.asyncio
    async def test_snooze(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "gc_snooze", "p": 42})

        with patch("handlers.graduation.execute", new_callable=AsyncMock):
            await handle_gc_snooze(callback_update, tg_context)

        text = callback_update.callback_query.edit_message_text.call_args[0][0]
        assert "Snoozed" in text


# ---------------------------------------------------------------------------
# Edit Name flow
# ---------------------------------------------------------------------------

class TestEditNameFlow:
    @pytest.mark.asyncio
    async def test_edit_start(self, callback_update, tg_context):
        callback_update.callback_query.data = json.dumps({"a": "gc_edit", "p": 42})

        result = await handle_gc_edit_start(callback_update, tg_context)

        assert result == GC_EDIT_NAME
        assert tg_context.user_data["gc_edit_pid"] == 42

    @pytest.mark.asyncio
    async def test_receive_name_success(self, message_update, tg_context, sample_proposal, tmp_path):
        tg_context.user_data["gc_edit_pid"] = 42
        message_update.message.text = "Revised Concept Name"

        mock_path = tmp_path / "Concepts" / "Revised-Concept-Name.md"
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        mock_path.write_text("")

        with (
            patch("handlers.graduation.execute", new_callable=AsyncMock),
            patch("handlers.graduation.query", new_callable=AsyncMock, return_value=[sample_proposal]),
            patch("handlers.graduation._graduate_proposal", new_callable=AsyncMock, return_value="path"),
        ):
            result = await receive_gc_name(message_update, tg_context)

        assert "gc_edit_pid" not in tg_context.user_data

    @pytest.mark.asyncio
    async def test_receive_name_no_pid(self, message_update, tg_context):
        result = await receive_gc_name(message_update, tg_context)
        # Should return ConversationHandler.END

    @pytest.mark.asyncio
    async def test_cancel_edit(self, message_update, tg_context):
        tg_context.user_data["gc_edit_pid"] = 42

        result = await cancel_gc_edit(message_update, tg_context)

        assert "gc_edit_pid" not in tg_context.user_data
        message_update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_registers_handlers(self):
        app = MagicMock()
        register(app)
        assert app.add_handler.call_count >= 4  # ConversationHandler + 3 callback handlers

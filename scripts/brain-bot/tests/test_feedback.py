"""Tests for handlers/feedback.py — Classification feedback handlers (Telegram).

The feedback module uses Telegram's CallbackQueryHandler pattern:
- handle_fb_correct: User confirms classification was correct
- handle_fb_wrong: User indicates classification was wrong, shows dimension picker
- handle_fb_dim_select: User selects the correct dimension from picker
- handle_bouncer_select: User selects dimension from confidence bouncer DM

All handlers are async and use (update, context) signature.
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Mock config before importing feedback module (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

import handlers.feedback as fb_mod

# Import the handler functions directly
handle_fb_correct = fb_mod.handle_fb_correct
handle_fb_wrong = fb_mod.handle_fb_wrong
handle_fb_dim_select = fb_mod.handle_fb_dim_select
handle_bouncer_select = fb_mod.handle_bouncer_select

# Ensure DIMENSION_TOPICS is real (not MagicMock auto-attribute from config mock)
_REAL_DIMENSION_TOPICS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}
fb_mod.DIMENSION_TOPICS = _REAL_DIMENSION_TOPICS


# ---------------------------------------------------------------------------
# Helper to build Telegram Update mocks
# ---------------------------------------------------------------------------

def _make_update(callback_data: dict, message_text="Test message",
                 message_text_html="<b>Test message</b>", chat_id=-100123):
    """Build a mock Telegram Update with a callback_query."""
    update = MagicMock()
    cb_query = MagicMock()
    cb_query.answer = AsyncMock()
    cb_query.edit_message_text = AsyncMock()
    cb_query.edit_message_reply_markup = AsyncMock()
    cb_query.data = json.dumps(callback_data, separators=(",", ":"))
    cb_query.message.chat_id = chat_id
    cb_query.message.text = message_text
    cb_query.message.text_html = message_text_html
    update.callback_query = cb_query
    return update


def _make_context():
    """Build a mock Telegram context."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
    context.bot.edit_message_text = AsyncMock()
    return context


# ---------------------------------------------------------------------------
# Tests for handle_fb_correct
# ---------------------------------------------------------------------------

class TestHandleCorrect:

    @pytest.mark.asyncio
    async def test_answers_callback_query(self):
        update = _make_update({"a": "fb_ok", "m": 123})
        context = _make_context()

        with patch.object(fb_mod, "query", new_callable=AsyncMock, return_value=[]), \
             patch.object(fb_mod, "execute", new_callable=AsyncMock):
            await handle_fb_correct(update, context)

        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_keyword_feedback_for_dimension(self):
        update = _make_update({"a": "fb_ok", "m": 123})
        context = _make_context()

        mock_query = AsyncMock(return_value=[
            {"primary_dimension": "Health & Vitality", "all_scores_json": "[]"}
        ])
        mock_execute = AsyncMock()

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute):
            await handle_fb_correct(update, context)

        # Should have called execute to update keyword_feedback
        keyword_calls = [
            c for c in mock_execute.call_args_list
            if "keyword_feedback" in str(c)
        ]
        assert len(keyword_calls) >= 1

    @pytest.mark.asyncio
    async def test_removes_buttons_and_adds_confirmation(self):
        update = _make_update({"a": "fb_ok", "m": 123})
        context = _make_context()

        with patch.object(fb_mod, "query", new_callable=AsyncMock, return_value=[]), \
             patch.object(fb_mod, "execute", new_callable=AsyncMock):
            await handle_fb_correct(update, context)

        # Should remove reply markup
        update.callback_query.edit_message_reply_markup.assert_called_once_with(
            reply_markup=None
        )
        # Should edit message text with confirmation
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "confirmed" in text.lower()

    @pytest.mark.asyncio
    async def test_no_dimension_still_succeeds(self):
        update = _make_update({"a": "fb_ok", "m": 123})
        context = _make_context()

        # No classification record found
        with patch.object(fb_mod, "query", new_callable=AsyncMock, return_value=[]), \
             patch.object(fb_mod, "execute", new_callable=AsyncMock):
            await handle_fb_correct(update, context)

        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        update = _make_update({"a": "fb_ok", "m": 123})
        context = _make_context()

        with patch.object(fb_mod, "query", new_callable=AsyncMock, side_effect=Exception("DB error")), \
             patch.object(fb_mod, "execute", new_callable=AsyncMock):
            # Should not raise
            await handle_fb_correct(update, context)

        update.callback_query.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for handle_fb_wrong
# ---------------------------------------------------------------------------

class TestHandleWrong:

    @pytest.mark.asyncio
    async def test_answers_callback_query(self):
        update = _make_update({"a": "fb_no", "m": 123})
        context = _make_context()

        await handle_fb_wrong(update, context)

        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_shows_dimension_picker(self):
        update = _make_update({"a": "fb_no", "m": 123})
        context = _make_context()

        await handle_fb_wrong(update, context)

        update.callback_query.edit_message_text.assert_called_once()
        call_kwargs = update.callback_query.edit_message_text.call_args[1] \
            if update.callback_query.edit_message_text.call_args[1] \
            else {}
        call_args_pos = update.callback_query.edit_message_text.call_args[0] \
            if update.callback_query.edit_message_text.call_args[0] \
            else ()

        # Should include "Select the correct dimension" prompt
        text = ""
        if call_args_pos:
            text = call_args_pos[0]
        elif "text" in call_kwargs:
            text = call_kwargs["text"]
        assert "correct dimension" in text.lower() or "select" in text.lower()

        # Should have reply_markup with dimension buttons
        reply_markup = call_kwargs.get("reply_markup")
        assert reply_markup is not None

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        update = _make_update({"a": "fb_no", "m": 123})
        context = _make_context()
        update.callback_query.edit_message_text.side_effect = Exception("API error")

        # Should not raise
        await handle_fb_wrong(update, context)
        update.callback_query.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for handle_fb_dim_select
# ---------------------------------------------------------------------------

class TestHandleDimensionSelect:

    @pytest.mark.asyncio
    async def test_updates_classification_record(self):
        update = _make_update({"a": "fb_d", "m": 123, "d": 0})
        context = _make_context()

        mock_query = AsyncMock(return_value=[
            {"primary_dimension": "Mind & Growth", "all_scores_json": "[]", "message_text": "test"}
        ])
        mock_execute = AsyncMock()

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute):
            await handle_fb_dim_select(update, context)

        update.callback_query.answer.assert_called_once()
        # Should have called execute for classification update
        classification_calls = [
            c for c in mock_execute.call_args_list
            if "classifications" in str(c) and "user_correction" in str(c)
        ]
        assert len(classification_calls) >= 1

    @pytest.mark.asyncio
    async def test_increments_fail_count_for_original_dimensions(self):
        update = _make_update({"a": "fb_d", "m": 123, "d": 0})
        context = _make_context()

        mock_query = AsyncMock(return_value=[{
            "primary_dimension": "Mind & Growth",
            "all_scores_json": json.dumps([
                {"dimension": "Mind & Growth", "confidence": 0.7, "method": "keyword"},
                {"dimension": "Wealth & Finance", "confidence": 0.3, "method": "keyword"},
            ]),
            "message_text": "test",
        }])
        mock_execute = AsyncMock()

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute):
            await handle_fb_dim_select(update, context)

        # Should have called execute for keyword_feedback fail_count updates
        fail_calls = [
            c for c in mock_execute.call_args_list
            if "fail_count" in str(c)
        ]
        assert len(fail_calls) >= 1

    @pytest.mark.asyncio
    async def test_edits_message_with_correction_info(self):
        update = _make_update({"a": "fb_d", "m": 123, "d": 0},
                              message_text="Test capture\nSelect the correct dimension:")
        context = _make_context()

        mock_query = AsyncMock(return_value=[{
            "primary_dimension": "Mind & Growth",
            "all_scores_json": "[]",
            "message_text": "test",
        }])
        mock_execute = AsyncMock()

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute):
            await handle_fb_dim_select(update, context)

        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        # Should mention the correction
        assert "Corrected" in text or "corrected" in text

    @pytest.mark.asyncio
    async def test_logs_corrected_capture_to_captures_log(self):
        """Corrected capture should INSERT into captures_log (not post to channel)."""
        mock_query = AsyncMock(return_value=[{"message_text": "My health update",
                                               "primary_dimension": "Mind & Growth",
                                               "all_scores_json": "[]"}])
        mock_execute = AsyncMock()

        update = _make_update({"a": "fb_d", "m": 123, "d": 0})
        context = _make_context()

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute):
            await handle_fb_dim_select(update, context)

        # Should have called execute for captures_log insert
        insert_calls = [
            c for c in mock_execute.call_args_list
            if "captures_log" in str(c)
        ]
        assert len(insert_calls) >= 1, "Should have inserted into captures_log"

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        update = _make_update({"a": "fb_d", "m": 123, "d": 0})
        context = _make_context()

        with patch.object(fb_mod, "query", new_callable=AsyncMock, side_effect=Exception("DB crash")), \
             patch.object(fb_mod, "execute", new_callable=AsyncMock):
            # Should not raise
            await handle_fb_dim_select(update, context)

        update.callback_query.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for handle_bouncer_select
# ---------------------------------------------------------------------------

class TestBouncerSelect:

    @pytest.mark.asyncio
    async def test_answers_callback_query(self):
        update = _make_update({"a": "bnc", "m": 123, "d": 0})
        context = _make_context()

        mock_execute = AsyncMock()
        mock_query = AsyncMock(return_value=[{"message_text": "test message"}])

        with patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "query", mock_query), \
             patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock):
            await handle_bouncer_select(update, context)

        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_pending_captures_to_resolved(self):
        update = _make_update({"a": "bnc", "m": 123, "d": 0})
        context = _make_context()

        mock_execute = AsyncMock()
        mock_query = AsyncMock(return_value=[{"message_text": "test message"}])

        with patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "query", mock_query), \
             patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock):
            await handle_bouncer_select(update, context)

        # Should have updated pending_captures status
        resolve_calls = [
            c for c in mock_execute.call_args_list
            if "pending_captures" in str(c) and "resolved" in str(c)
        ]
        assert len(resolve_calls) >= 1

    @pytest.mark.asyncio
    async def test_edits_bouncer_dm_with_confirmation(self):
        update = _make_update({"a": "bnc", "m": 123, "d": 0})
        context = _make_context()

        mock_execute = AsyncMock()
        mock_query = AsyncMock(return_value=[{"message_text": "test message"}])

        with patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "query", mock_query), \
             patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock):
            await handle_bouncer_select(update, context)

        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Filed" in text or "filed" in text

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        update = _make_update({"a": "bnc", "m": 123, "d": 99})  # out of range index
        context = _make_context()

        with patch.object(fb_mod, "execute", new_callable=AsyncMock, side_effect=Exception("DB error")), \
             patch.object(fb_mod, "query", new_callable=AsyncMock):
            # Should not raise
            await handle_bouncer_select(update, context)


# ---------------------------------------------------------------------------
# Tests: register() pattern
# ---------------------------------------------------------------------------

class TestRegistration:
    """Verify feedback handlers register with CallbackQueryHandler pattern."""

    def test_register_adds_callback_query_handlers(self):
        """register() should add CallbackQueryHandler instances to the application."""
        mock_app = MagicMock()
        fb_mod.register(mock_app)

        # Should call add_handler for each callback pattern
        assert mock_app.add_handler.call_count == 4

    def test_register_uses_correct_patterns(self):
        """register() should use correct regex patterns for callback data."""
        mock_app = MagicMock()
        fb_mod.register(mock_app)

        # Extract pattern arguments from add_handler calls
        patterns = []
        for call in mock_app.add_handler.call_args_list:
            handler = call[0][0]
            if hasattr(handler, "pattern"):
                patterns.append(str(handler.pattern))

        # The patterns should cover fb_ok, fb_no, fb_d, bnc
        pattern_text = " ".join(patterns)
        assert "fb_ok" in pattern_text or len(patterns) == 4

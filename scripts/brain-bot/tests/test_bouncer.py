"""Tests for the confidence bouncer feature (Telegram).

Tests cover:
1. Low confidence triggers bouncer (DM sent to user via context.bot)
2. High confidence bypasses bouncer (normal routing)
3. Bouncer resolution routes to correct dimension
4. Pending capture inserted into DB
5. Bouncer action handler (feedback.py handle_bouncer_select)
6. Timeout auto-files correctly (scheduled.py job_resolve_pending_captures)
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())

from core.classifier import ClassificationResult, DimensionScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REAL_DIMENSION_TOPICS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}


def _make_update(text="test message", user_id=12345, chat_id=-100123, msg_id=1234):
    """Build a mock Telegram Update for capture handler."""
    update = MagicMock()
    update.message.text = text
    update.message.message_id = msg_id
    update.message.message_thread_id = 1  # inbox topic
    update.message.reply_text = AsyncMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    return update


def _make_context():
    """Build a mock Telegram context."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
    context.bot.edit_message_text = AsyncMock()
    context.args = []
    context.application.create_task = MagicMock()
    return context


def _make_low_result(confidence=0.45):
    return ClassificationResult(
        matches=[
            DimensionScore(dimension="Health & Vitality", confidence=confidence, method="embedding"),
            DimensionScore(dimension="Mind & Growth", confidence=0.30, method="embedding"),
        ],
        is_actionable=False,
    )


def _make_high_result(confidence=0.85):
    return ClassificationResult(
        matches=[DimensionScore(dimension="Health & Vitality", confidence=confidence, method="keyword")],
        is_noise=False,
        is_actionable=False,
    )


# ---------------------------------------------------------------------------
# Test: Low confidence triggers bouncer DM
# ---------------------------------------------------------------------------

class TestLowConfidenceTriggersBouncer:

    @pytest.mark.asyncio
    async def test_low_confidence_sends_dm(self):
        """When confidence < threshold, a DM is sent to the user via context.bot."""
        from handlers.capture import _handle_low_confidence

        update = _make_update(text="maybe something about health")
        context = _make_context()
        result = _make_low_result()

        with patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- test capture"), \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.DIMENSION_TOPICS", _REAL_DIMENSION_TOPICS):
            await _handle_low_confidence(update, context, result)

        # Verify DM was sent to the user
        context.bot.send_message.assert_called_once()
        call_kwargs = context.bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == 12345  # user_id
        assert "Unsure where this goes" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_low_confidence_still_saves_to_vault(self):
        """Low-confidence captures are still saved to daily note and inbox."""
        from handlers.capture import _handle_low_confidence

        update = _make_update(text="something vague")
        context = _make_context()
        result = _make_low_result()

        mock_append = MagicMock()
        mock_inbox = MagicMock()

        with patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.append_to_daily_note", mock_append), \
             patch("handlers.capture.create_inbox_entry", mock_inbox), \
             patch("handlers.capture.format_capture_line", return_value="- test"), \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.DIMENSION_TOPICS", _REAL_DIMENSION_TOPICS):
            await _handle_low_confidence(update, context, result)

        mock_append.assert_called_once()
        mock_inbox.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_user_returns_early(self):
        """If text or user triggers an exception, low confidence handler catches it."""
        from handlers.capture import _handle_low_confidence

        # Create update where message.text will raise AttributeError
        update = MagicMock()
        update.message.text = None
        update.message.message_id = 123

        context = _make_context()
        result = _make_low_result()

        # Should not raise (handler has try/except)
        with patch("handlers.capture.run_in_executor", new=AsyncMock()), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.DIMENSION_TOPICS", _REAL_DIMENSION_TOPICS):
            await _handle_low_confidence(update, context, result)

        # No DM should be sent since text is None
        context.bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Test: High confidence bypasses bouncer
# ---------------------------------------------------------------------------

class TestHighConfidenceBypassesBouncer:

    @pytest.mark.asyncio
    async def test_high_confidence_does_not_trigger_bouncer(self):
        """Messages with confidence >= threshold should NOT trigger bouncer."""
        from handlers.capture import handle_capture

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = _make_high_result()

        update = _make_update(text="going to the gym")
        context = _make_context()

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- gym"), \
             patch("handlers.capture.format_capture_confirmation", return_value=("confirmed", None)), \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.TOPICS", {"brain-inbox": 1}), \
             patch("handlers.capture.OWNER_TELEGRAM_ID", 12345), \
             patch("handlers.capture.GROUP_CHAT_ID", -100123), \
             patch("handlers.capture.config") as mock_cfg, \
             patch("handlers.capture._handle_low_confidence", new_callable=AsyncMock) as mock_bouncer:
            mock_cfg.CONFIDENCE_THRESHOLD = 0.60
            await handle_capture(update, context)

        mock_bouncer.assert_not_called()

    @pytest.mark.asyncio
    async def test_noise_does_not_trigger_bouncer(self):
        """Noise messages should be filtered before bouncer is checked."""
        from handlers.capture import handle_capture

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = ClassificationResult(is_noise=True)

        update = _make_update(text="hello")
        context = _make_context()

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.TOPICS", {"brain-inbox": 1}), \
             patch("handlers.capture.OWNER_TELEGRAM_ID", 12345), \
             patch("handlers.capture.GROUP_CHAT_ID", -100123), \
             patch("handlers.capture._handle_low_confidence", new_callable=AsyncMock) as mock_bouncer:
            await handle_capture(update, context)

        mock_bouncer.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Bouncer resolution routes to correct dimension
# ---------------------------------------------------------------------------

class TestBouncerResolution:

    @pytest.mark.asyncio
    async def test_logs_to_captures_log(self):
        """process_bouncer_resolution logs to captures_log."""
        from handlers.capture import process_bouncer_resolution

        mock_execute = AsyncMock()

        with patch("handlers.capture.execute", mock_execute):
            await process_bouncer_resolution(
                "My gym session notes", 12345,
                "Health & Vitality", None,
            )

        # Should have called execute for captures_log insert
        insert_calls = [
            c for c in mock_execute.call_args_list
            if "captures_log" in str(c)
        ]
        assert len(insert_calls) >= 1

    @pytest.mark.asyncio
    async def test_updates_classification_record(self):
        """Resolution updates the classifications table."""
        from handlers.capture import process_bouncer_resolution

        mock_execute = AsyncMock()

        with patch("handlers.capture.execute", mock_execute):
            await process_bouncer_resolution(
                "test text", 456, "Mind & Growth", None,
            )

        # Should have called execute for classifications update
        classification_calls = [
            c for c in mock_execute.call_args_list
            if "classifications" in str(c)
        ]
        assert len(classification_calls) >= 1


# ---------------------------------------------------------------------------
# Test: Pending capture DB insertion
# ---------------------------------------------------------------------------

class TestPendingCaptureDbInsertion:

    @pytest.mark.asyncio
    async def test_inserts_pending_capture_into_db(self):
        """_handle_low_confidence inserts a row into pending_captures."""
        from handlers.capture import _handle_low_confidence

        update = _make_update(text="ambiguous text")
        context = _make_context()
        result = _make_low_result()

        mock_execute = AsyncMock()

        with patch("handlers.capture.run_in_executor", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- test"), \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", mock_execute), \
             patch("handlers.capture.DIMENSION_TOPICS", _REAL_DIMENSION_TOPICS):
            await _handle_low_confidence(update, context, result)

        # Should have inserted into pending_captures
        pending_calls = [
            c for c in mock_execute.call_args_list
            if "pending_captures" in str(c) and "INSERT" in str(c)
        ]
        assert len(pending_calls) >= 1


# ---------------------------------------------------------------------------
# Test: Bouncer action handler (feedback.py)
# ---------------------------------------------------------------------------

class TestBouncerActionHandler:

    @pytest.mark.asyncio
    async def test_bouncer_select_updates_dm_and_routes(self):
        """Selecting a dimension from bouncer DM resolves and routes."""
        import handlers.feedback as fb_mod
        fb_mod.DIMENSION_TOPICS = _REAL_DIMENSION_TOPICS

        update = MagicMock()
        cb_query = MagicMock()
        cb_query.answer = AsyncMock()
        cb_query.edit_message_text = AsyncMock()
        cb_query.data = json.dumps({"a": "bnc", "m": 123, "d": 0}, separators=(",", ":"))
        update.callback_query = cb_query

        context = _make_context()

        mock_execute = AsyncMock()
        mock_query = AsyncMock(return_value=[{"message_text": "health stuff"}])

        with patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "query", mock_query), \
             patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock):
            await fb_mod.handle_bouncer_select(update, context)

        cb_query.answer.assert_called_once()
        # Should update DM message with confirmation
        cb_query.edit_message_text.assert_called_once()
        call_args = cb_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Filed" in text

    @pytest.mark.asyncio
    async def test_bouncer_select_missing_dim_returns_early(self):
        """If dim_idx is out of range, handler returns without action."""
        import handlers.feedback as fb_mod
        fb_mod.DIMENSION_TOPICS = _REAL_DIMENSION_TOPICS

        update = MagicMock()
        cb_query = MagicMock()
        cb_query.answer = AsyncMock()
        cb_query.edit_message_text = AsyncMock()
        # d=99 is out of range (only 6 dimensions)
        cb_query.data = json.dumps({"a": "bnc", "m": 123, "d": 99}, separators=(",", ":"))
        update.callback_query = cb_query

        context = _make_context()

        with patch.object(fb_mod, "execute", new_callable=AsyncMock) as mock_execute:
            await fb_mod.handle_bouncer_select(update, context)

        cb_query.answer.assert_called_once()
        mock_execute.assert_not_called()
        cb_query.edit_message_text.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Timeout auto-files correctly
# ---------------------------------------------------------------------------

class TestTimeoutAutoFiles:

    @pytest.mark.asyncio
    async def test_resolves_timed_out_captures(self):
        """job_resolve_pending_captures processes expired pending captures."""
        from handlers.scheduled import job_resolve_pending_captures

        pending_rows = [
            {
                "id": 1,
                "message_text": "ambiguous text",
                "message_ts": "12345",
                "primary_dimension": "Health & Vitality",
                "channel_id": "-100123",
                "bouncer_dm_ts": "dm_ts_1",
                "bouncer_dm_channel": "DM_CH_1",
            }
        ]

        mock_query = AsyncMock(return_value=pending_rows)
        mock_execute = AsyncMock()

        mock_context = MagicMock()
        mock_context.bot = MagicMock()
        mock_context.bot.edit_message_text = AsyncMock()

        with patch("handlers.scheduled.query", mock_query), \
             patch("handlers.scheduled.execute", mock_execute), \
             patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock) as mock_resolve, \
             patch("config.BOUNCER_TIMEOUT_MINUTES", 15):
            await job_resolve_pending_captures(mock_context)

        # Should have called query for pending captures
        mock_query.assert_called_once()

        # Should have called execute to update status
        status_calls = [
            c for c in mock_execute.call_args_list
            if "pending_captures" in str(c) and "timeout" in str(c)
        ]
        assert len(status_calls) >= 1

    @pytest.mark.asyncio
    async def test_no_pending_captures_is_noop(self):
        """When no captures are pending, the job does nothing."""
        from handlers.scheduled import job_resolve_pending_captures

        mock_query = AsyncMock(return_value=[])
        mock_execute = AsyncMock()

        mock_context = MagicMock()
        mock_context.bot = MagicMock()

        with patch("handlers.scheduled.query", mock_query), \
             patch("handlers.scheduled.execute", mock_execute), \
             patch("config.BOUNCER_TIMEOUT_MINUTES", 15):
            await job_resolve_pending_captures(mock_context)

        mock_query.assert_called_once()
        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_dm_info_still_resolves(self):
        """If bouncer_dm_ts is missing, routing still happens."""
        from handlers.scheduled import job_resolve_pending_captures

        pending_rows = [
            {
                "id": 2,
                "message_text": "another text",
                "message_ts": "67890",
                "primary_dimension": "Mind & Growth",
                "channel_id": "-100123",
                "bouncer_dm_ts": None,
                "bouncer_dm_channel": None,
            }
        ]

        mock_query = AsyncMock(return_value=pending_rows)
        mock_execute = AsyncMock()

        mock_context = MagicMock()
        mock_context.bot = MagicMock()

        with patch("handlers.scheduled.query", mock_query), \
             patch("handlers.scheduled.execute", mock_execute), \
             patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock) as mock_resolve, \
             patch("config.BOUNCER_TIMEOUT_MINUTES", 15):
            await job_resolve_pending_captures(mock_context)

        # Should still route via process_bouncer_resolution
        mock_resolve.assert_called_once()

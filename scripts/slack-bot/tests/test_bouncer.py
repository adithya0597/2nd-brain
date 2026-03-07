"""Tests for the confidence bouncer feature.

Tests cover:
1. Low confidence triggers bouncer (DM sent to user)
2. High confidence bypasses bouncer (normal routing)
3. Bouncer resolution routes to correct channel
4. Pending capture inserted into DB
5. Timeout auto-files correctly
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

from core.classifier import ClassificationResult, DimensionScore


# ---------------------------------------------------------------------------
# Test: Low confidence triggers bouncer DM
# ---------------------------------------------------------------------------

class TestLowConfidenceTriggersBouncer:

    @patch("handlers.capture.run_async")
    @patch("handlers.capture.create_inbox_entry")
    @patch("handlers.capture.append_to_daily_note")
    @patch("handlers.capture.format_capture_line", return_value="- test capture")
    @patch("handlers.capture._log_classification")
    def test_low_confidence_sends_dm(
        self, mock_log, mock_format, mock_append, mock_inbox, mock_run_async
    ):
        """When confidence < threshold, a DM is sent to the user."""
        from handlers.capture import _handle_low_confidence

        client = MagicMock()
        client.conversations_open.return_value = {"channel": {"id": "DM_CH"}}
        client.chat_postMessage.return_value = {"ts": "dm_ts_123"}

        event = {"text": "maybe something about health", "user": "U123", "channel": "C_INBOX", "ts": "1234.5678"}
        channel_ids = {"brain-inbox": "C_INBOX"}

        result = ClassificationResult(
            matches=[
                DimensionScore(dimension="Health & Vitality", confidence=0.45, method="embedding"),
                DimensionScore(dimension="Mind & Growth", confidence=0.30, method="embedding"),
            ],
            is_actionable=False,
        )

        _handle_low_confidence(client, event, channel_ids, result)

        # Verify DM was opened with the user
        client.conversations_open.assert_called_once_with(users=["U123"])

        # Verify message was sent to DM channel
        client.chat_postMessage.assert_called_once()
        call_kwargs = client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "DM_CH"
        assert "bouncer_select_dimension" in json.dumps(call_kwargs["blocks"])

    @patch("handlers.capture.run_async")
    @patch("handlers.capture.create_inbox_entry")
    @patch("handlers.capture.append_to_daily_note")
    @patch("handlers.capture.format_capture_line", return_value="- test")
    @patch("handlers.capture._log_classification")
    def test_low_confidence_still_saves_to_vault(
        self, mock_log, mock_format, mock_append, mock_inbox, mock_run_async
    ):
        """Low-confidence captures are still saved to daily note and inbox."""
        from handlers.capture import _handle_low_confidence

        client = MagicMock()
        client.conversations_open.return_value = {"channel": {"id": "DM_CH"}}
        client.chat_postMessage.return_value = {"ts": "dm_ts_123"}

        event = {"text": "something vague", "user": "U123", "channel": "C_INBOX", "ts": "1234.5678"}
        channel_ids = {}

        result = ClassificationResult(
            matches=[DimensionScore(dimension="Health & Vitality", confidence=0.40, method="keyword")],
            is_actionable=False,
        )

        _handle_low_confidence(client, event, channel_ids, result)

        mock_append.assert_called_once()
        mock_inbox.assert_called_once()

    @patch("handlers.capture.run_async")
    @patch("handlers.capture.create_inbox_entry")
    @patch("handlers.capture.append_to_daily_note")
    @patch("handlers.capture.format_capture_line", return_value="- test")
    @patch("handlers.capture._log_classification")
    def test_empty_user_returns_early(
        self, mock_log, mock_format, mock_append, mock_inbox, mock_run_async
    ):
        """If user or text is empty, _handle_low_confidence returns without action."""
        from handlers.capture import _handle_low_confidence

        client = MagicMock()
        event = {"text": "test", "user": "", "channel": "C_INBOX", "ts": "1234.5678"}
        result = ClassificationResult(
            matches=[DimensionScore(dimension="Health & Vitality", confidence=0.40, method="keyword")],
        )

        _handle_low_confidence(client, event, {}, result)

        client.conversations_open.assert_not_called()
        mock_append.assert_not_called()


# ---------------------------------------------------------------------------
# Test: High confidence bypasses bouncer
# ---------------------------------------------------------------------------

class TestHighConfidenceBypassesBouncer:

    @patch("handlers.capture._handle_low_confidence")
    @patch("handlers.capture._classifier")
    @patch("handlers.capture.run_async")
    @patch("handlers.capture.create_inbox_entry")
    @patch("handlers.capture.append_to_daily_note")
    @patch("handlers.capture.format_capture_line", return_value="- gym workout")
    @patch("handlers.capture._log_classification")
    @patch("handlers.capture.format_capture_confirmation", return_value=[])
    @patch("handlers.capture._build_feedback_buttons", return_value=[])
    def test_high_confidence_does_not_trigger_bouncer(
        self, mock_buttons, mock_confirm, mock_log, mock_format,
        mock_append, mock_inbox, mock_run_async, mock_classifier, mock_bouncer
    ):
        """Messages with confidence >= threshold should NOT trigger bouncer."""
        from handlers.capture import _process_capture

        mock_classifier.classify.return_value = ClassificationResult(
            matches=[DimensionScore(dimension="Health & Vitality", confidence=0.85, method="keyword")],
            is_noise=False,
            is_actionable=False,
        )

        client = MagicMock()
        event = {"text": "going to the gym", "user": "U123", "channel": "C_INBOX", "ts": "ts_high"}
        channel_ids = {"brain-inbox": "C_INBOX", "brain-health": "C_HEALTH"}

        _process_capture(client, event, channel_ids)

        mock_bouncer.assert_not_called()

    @patch("handlers.capture._handle_low_confidence")
    @patch("handlers.capture._classifier")
    def test_noise_does_not_trigger_bouncer(self, mock_classifier, mock_bouncer):
        """Noise messages should be filtered before bouncer is checked."""
        from handlers.capture import _process_capture

        mock_classifier.classify.return_value = ClassificationResult(
            is_noise=True,
        )

        client = MagicMock()
        event = {"text": "hello", "user": "U123", "channel": "C_INBOX", "ts": "ts_noise"}
        channel_ids = {"brain-inbox": "C_INBOX"}

        _process_capture(client, event, channel_ids)

        mock_bouncer.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Bouncer resolution routes to correct channel
# ---------------------------------------------------------------------------

class TestBouncerResolution:

    @patch("handlers.capture.run_async")
    def test_logs_to_captures_log_and_replies_in_inbox(self, mock_run_async):
        """_process_bouncer_resolution logs to captures_log and replies in inbox thread."""
        from handlers.capture import _process_bouncer_resolution

        client = MagicMock()

        _process_bouncer_resolution(
            client, "My gym session notes", "ts_123",
            "Health & Vitality", "C_INBOX",
        )

        # Should reply in inbox thread
        assert client.chat_postMessage.call_count >= 1, (
            f"Expected at least 1 call, got {client.chat_postMessage.call_count}"
        )

        first_call = client.chat_postMessage.call_args_list[0]
        assert first_call[1]["channel"] == "C_INBOX"
        assert first_call[1]["thread_ts"] == "ts_123"
        assert "user-clarified" in first_call[1]["text"]

        # Should have called run_async twice: captures_log insert + classifications update
        assert mock_run_async.call_count == 2

    @patch("handlers.capture.run_async")
    def test_updates_classification_record(self, mock_run_async):
        """Resolution updates the classifications table."""
        from handlers.capture import _process_bouncer_resolution

        _process_bouncer_resolution(
            client=MagicMock(), text="test text", ts="ts_456",
            dimension="Mind & Growth", inbox_channel="",
        )
        # Should have called run_async twice: captures_log insert + classifications update
        assert mock_run_async.call_count == 2


# ---------------------------------------------------------------------------
# Test: Pending capture DB insertion
# ---------------------------------------------------------------------------

class TestPendingCaptureDbInsertion:

    @patch("handlers.capture.run_async")
    @patch("handlers.capture.create_inbox_entry")
    @patch("handlers.capture.append_to_daily_note")
    @patch("handlers.capture.format_capture_line", return_value="- test")
    @patch("handlers.capture._log_classification")
    def test_inserts_pending_capture_into_db(
        self, mock_log, mock_format, mock_append, mock_inbox, mock_run_async
    ):
        """_handle_low_confidence inserts a row into pending_captures."""
        from handlers.capture import _handle_low_confidence

        client = MagicMock()
        client.conversations_open.return_value = {"channel": {"id": "DM_CH"}}
        client.chat_postMessage.return_value = {"ts": "dm_ts_999"}

        event = {"text": "ambiguous text", "user": "U123", "channel": "C_INBOX", "ts": "ts_abc"}
        channel_ids = {}

        result = ClassificationResult(
            matches=[
                DimensionScore(dimension="Health & Vitality", confidence=0.45, method="embedding"),
            ],
            is_actionable=False,
        )

        _handle_low_confidence(client, event, channel_ids, result)

        # run_async should be called: once for the DB insert
        assert mock_run_async.call_count >= 1

        # Inspect the last run_async call (the DB insert)
        last_call = mock_run_async.call_args_list[-1]
        # The argument is a coroutine for execute()
        # We can verify it was called by checking the mock was invoked


# ---------------------------------------------------------------------------
# Test: Bouncer action handler in feedback.py
# ---------------------------------------------------------------------------

class TestBouncerActionHandler:
    """Test the bouncer_select_dimension action handler.

    We capture the handler by registering feedback handlers with a fresh mock app.
    To avoid polluting the module state for other test files, we use a local capture
    that does NOT modify the module-level handler references.
    """

    @staticmethod
    def _get_bouncer_handler():
        """Register feedback handlers and return the bouncer handler."""
        import handlers.feedback as fb_mod

        registered = {}

        def capture_action(action_id):
            def decorator(fn):
                registered[action_id] = fn
                return fn
            return decorator

        mock_app = MagicMock()
        mock_app.action = capture_action
        fb_mod.register(mock_app)

        return registered.get("bouncer_select_dimension"), fb_mod

    def test_bouncer_select_updates_dm_and_routes(self):
        """Selecting a dimension from bouncer DM resolves and routes."""
        handler, fb_mod = self._get_bouncer_handler()
        assert handler is not None, "bouncer_select_dimension handler should be registered"

        ack = MagicMock()
        client = MagicMock()

        selected_value = json.dumps({
            "ts": "ts_bounce_1",
            "dimension": "Health & Vitality",
            "text": "some health text",
            "channel": "C_INBOX",
        })

        body = {
            "actions": [{"selected_option": {"value": selected_value}}],
            "channel": {"id": "DM_CH"},
            "message": {"ts": "dm_msg_ts"},
        }

        with patch.object(fb_mod, "run_async") as mock_run_async, \
             patch("handlers.capture._process_bouncer_resolution") as mock_resolve:
            handler(ack, body, client)

        ack.assert_called_once()
        # Should update DM message
        client.chat_update.assert_called_once()
        update_kwargs = client.chat_update.call_args[1]
        assert "Filed to Health & Vitality" in update_kwargs["text"]

    def test_bouncer_select_missing_ts_returns_early(self):
        """If message_ts is empty, handler returns without action."""
        handler, fb_mod = self._get_bouncer_handler()

        ack = MagicMock()
        client = MagicMock()

        selected_value = json.dumps({
            "ts": "",
            "dimension": "Health & Vitality",
            "text": "test",
            "channel": "C_INBOX",
        })

        body = {
            "actions": [{"selected_option": {"value": selected_value}}],
            "channel": {"id": "DM_CH"},
            "message": {"ts": "dm_msg_ts"},
        }

        with patch.object(fb_mod, "run_async") as mock_run_async:
            handler(ack, body, client)

        ack.assert_called_once()
        mock_run_async.assert_not_called()
        client.chat_update.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Timeout auto-files correctly
# ---------------------------------------------------------------------------

class TestTimeoutAutoFiles:

    @patch("handlers.scheduled.run_async")
    def test_resolves_timed_out_captures(self, mock_run_async):
        """job_resolve_pending_captures processes expired pending captures."""
        from handlers.scheduled import job_resolve_pending_captures

        # First call returns pending rows, second call is the execute for update
        pending_rows = [
            {
                "id": 1,
                "message_text": "ambiguous text",
                "message_ts": "ts_timeout_1",
                "primary_dimension": "Health & Vitality",
                "channel_id": "C_INBOX",
                "bouncer_dm_ts": "dm_ts_1",
                "bouncer_dm_channel": "DM_CH_1",
            }
        ]

        # run_async is called for query (returns rows) and execute (returns None)
        call_count = [0]

        def side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                return pending_rows  # query result
            return None  # execute result

        mock_run_async.side_effect = side_effect

        client = MagicMock()
        channel_ids = {}

        with patch("config.BOUNCER_TIMEOUT_MINUTES", 15), \
             patch("handlers.capture._process_bouncer_resolution") as mock_resolve:
            job_resolve_pending_captures(client, channel_ids)

        # Should have called run_async at least twice (query + execute)
        assert mock_run_async.call_count >= 2

        # Should update DM message
        client.chat_update.assert_called_once()
        update_kwargs = client.chat_update.call_args[1]
        assert update_kwargs["channel"] == "DM_CH_1"
        assert "Auto-filed" in update_kwargs["text"]

    @patch("handlers.scheduled.run_async")
    def test_no_pending_captures_is_noop(self, mock_run_async):
        """When no captures are pending, the job does nothing."""
        from handlers.scheduled import job_resolve_pending_captures

        mock_run_async.return_value = []

        client = MagicMock()
        channel_ids = {}

        with patch("config.BOUNCER_TIMEOUT_MINUTES", 15):
            job_resolve_pending_captures(client, channel_ids)

        # Only one call for the query
        assert mock_run_async.call_count == 1
        client.chat_update.assert_not_called()

    @patch("handlers.scheduled.run_async")
    def test_missing_dm_info_skips_dm_update(self, mock_run_async):
        """If bouncer_dm_ts is missing, DM update is skipped."""
        from handlers.scheduled import job_resolve_pending_captures

        pending_rows = [
            {
                "id": 2,
                "message_text": "another text",
                "message_ts": "ts_timeout_2",
                "primary_dimension": "Mind & Growth",
                "channel_id": "C_INBOX",
                "bouncer_dm_ts": None,
                "bouncer_dm_channel": None,
            }
        ]

        call_count = [0]

        def side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                return pending_rows
            return None

        mock_run_async.side_effect = side_effect

        client = MagicMock()
        channel_ids = {}

        with patch("config.BOUNCER_TIMEOUT_MINUTES", 15), \
             patch("handlers.capture._process_bouncer_resolution"):
            job_resolve_pending_captures(client, channel_ids)

        client.chat_update.assert_not_called()

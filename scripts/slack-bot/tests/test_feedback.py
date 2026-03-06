"""Tests for handlers/feedback.py — Classification feedback handlers."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing feedback module
_mock_config = MagicMock()
_mock_config.DIMENSION_CHANNELS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}
sys.modules.setdefault("config", _mock_config)

# We need handlers.commands._channel_ids to be importable.
# Import the module and register handlers once.
import handlers.feedback as fb_mod

# Register handlers with a mock app to capture the inner functions
_registered_handlers = {}

def _capture_action(action_id):
    def decorator(fn):
        _registered_handlers[action_id] = fn
        return fn
    return decorator

_mock_app = MagicMock()
_mock_app.action = _capture_action
fb_mod.register(_mock_app)

handle_correct = _registered_handlers["feedback_correct"]
handle_wrong = _registered_handlers["feedback_wrong"]
handle_dimension_select = _registered_handlers["feedback_select_dimension"]


# ---------------------------------------------------------------------------
# Helper to build Slack body dicts
# ---------------------------------------------------------------------------

def _make_body(action_value: dict, channel_id="C123", message_ts="1234567890.123456",
               blocks=None, selected_option_value=None):
    """Build a mock Slack action body."""
    body = {
        "channel": {"id": channel_id},
        "message": {
            "ts": message_ts,
            "blocks": blocks or [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}},
                {"type": "actions", "block_id": "feedback_abc", "elements": []},
            ],
        },
    }
    if selected_option_value is not None:
        body["actions"] = [{"selected_option": {"value": json.dumps(selected_option_value)}}]
    else:
        body["actions"] = [{"value": json.dumps(action_value)}]
    return body


# ---------------------------------------------------------------------------
# Tests for handle_correct
# ---------------------------------------------------------------------------

class TestHandleCorrect:

    @patch("handlers.feedback.run_async")
    def test_updates_keyword_feedback_for_each_dimension(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": ["Health & Vitality", "Mind & Growth"]})

        handle_correct(ack, body, client)

        ack.assert_called_once()
        # Should call run_async twice (once per dimension)
        assert mock_run_async.call_count == 2

    @patch("handlers.feedback.run_async")
    def test_removes_feedback_block_and_adds_confirmation(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": ["Health & Vitality"]})

        handle_correct(ack, body, client)

        client.chat_update.assert_called_once()
        call_kwargs = client.chat_update.call_args[1]
        assert call_kwargs["channel"] == "C123"
        blocks = call_kwargs["blocks"]
        # Verify feedback block was removed
        feedback_blocks = [b for b in blocks if b.get("block_id", "").startswith("feedback_")]
        assert len(feedback_blocks) == 0
        # Verify confirmation context was added
        context_blocks = [b for b in blocks if b.get("type") == "context"]
        assert len(context_blocks) == 1
        assert "confirmed" in context_blocks[0]["elements"][0]["text"].lower()

    @patch("handlers.feedback.run_async")
    def test_no_dimensions_still_succeeds(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": []})

        handle_correct(ack, body, client)

        ack.assert_called_once()
        mock_run_async.assert_not_called()
        # Still updates the message
        client.chat_update.assert_called_once()

    @patch("handlers.feedback.run_async")
    def test_missing_channel_skips_update(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": ["Health & Vitality"]})
        body["channel"] = {}  # No channel ID

        handle_correct(ack, body, client)

        ack.assert_called_once()
        client.chat_update.assert_not_called()

    @patch("handlers.feedback.run_async", side_effect=Exception("DB error"))
    def test_exception_does_not_propagate(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": ["Health & Vitality"]})

        # Should not raise
        handle_correct(ack, body, client)
        ack.assert_called_once()

    @patch("handlers.feedback.run_async")
    def test_single_dimension_calls_run_async_once(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": ["Purpose & Impact"]})

        handle_correct(ack, body, client)

        assert mock_run_async.call_count == 1

    @patch("handlers.feedback.run_async")
    def test_chat_update_text_says_confirmed(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": []})

        handle_correct(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        assert call_kwargs["text"] == "Classification confirmed"


# ---------------------------------------------------------------------------
# Tests for handle_wrong
# ---------------------------------------------------------------------------

class TestHandleWrong:

    def test_builds_dimension_picker_with_all_dimensions(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": ["Health & Vitality"]})

        handle_wrong(ack, body, client)

        ack.assert_called_once()
        client.chat_update.assert_called_once()
        call_kwargs = client.chat_update.call_args[1]
        blocks = call_kwargs["blocks"]

        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 1
        select = action_blocks[0]["elements"][0]
        assert select["type"] == "static_select"
        assert select["action_id"] == "feedback_select_dimension"

        options = select["options"]
        assert len(options) == 6
        dim_names = {o["text"]["text"] for o in options}
        assert "Health & Vitality" in dim_names
        assert "Systems & Environment" in dim_names

    def test_options_contain_original_dimensions_in_value(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "ts123", "dimensions": ["Relationships"]})

        handle_wrong(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        blocks = call_kwargs["blocks"]
        action_block = [b for b in blocks if b.get("type") == "actions"][0]
        first_option = action_block["elements"][0]["options"][0]
        option_data = json.loads(first_option["value"])
        assert option_data["ts"] == "ts123"
        assert option_data["original_dimensions"] == ["Relationships"]

    def test_removes_existing_feedback_block(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": []})

        handle_wrong(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        blocks = call_kwargs["blocks"]
        feedback_blocks = [b for b in blocks if b.get("block_id", "").startswith("feedback_")]
        assert len(feedback_blocks) == 0

    def test_correction_block_id_includes_ts(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "my_ts_42", "dimensions": []})

        handle_wrong(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        blocks = call_kwargs["blocks"]
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert action_blocks[0]["block_id"] == "correction_my_ts_42"

    def test_missing_channel_skips_update(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": []})
        body["channel"] = {}

        handle_wrong(ack, body, client)

        ack.assert_called_once()
        client.chat_update.assert_not_called()

    def test_exception_does_not_propagate(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": []})
        client.chat_update.side_effect = Exception("API error")

        handle_wrong(ack, body, client)
        ack.assert_called_once()

    def test_chat_update_text_says_select(self):
        ack = MagicMock()
        client = MagicMock()
        body = _make_body({"ts": "123", "dimensions": []})

        handle_wrong(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        assert call_kwargs["text"] == "Select the correct dimension"


# ---------------------------------------------------------------------------
# Tests for handle_dimension_select
# ---------------------------------------------------------------------------

class TestHandleDimensionSelect:

    @patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"})
    @patch("handlers.feedback.run_async")
    def test_updates_classification_record(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": ["Mind & Growth"],
        }
        body = _make_body({}, selected_option_value=selected_value)

        handle_dimension_select(ack, body, client)

        ack.assert_called_once()
        # 1 for classifications update + 1 for keyword_feedback + 1 for query = 3
        assert mock_run_async.call_count >= 2

    @patch("handlers.commands._channel_ids", {"brain-growth": "C_GROWTH"})
    @patch("handlers.feedback.run_async")
    def test_increments_fail_count_for_original_dimensions(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Mind & Growth",
            "original_dimensions": ["Health & Vitality", "Wealth & Finance"],
        }
        body = _make_body({}, selected_option_value=selected_value)

        handle_dimension_select(ack, body, client)

        # 1 for classifications + 2 for keyword_feedback (one per original dim) + 1 query = 4
        assert mock_run_async.call_count >= 3

    @patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"})
    @patch("handlers.feedback.run_async")
    def test_edits_original_slack_message(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": ["Mind & Growth"],
        }
        body = _make_body(
            {},
            selected_option_value=selected_value,
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": "Test"}},
                {"type": "actions", "block_id": "correction_ts123", "elements": []},
            ],
        )

        handle_dimension_select(ack, body, client)

        client.chat_update.assert_called_once()
        call_kwargs = client.chat_update.call_args[1]
        blocks = call_kwargs["blocks"]

        # Correction block should be removed
        correction_blocks = [b for b in blocks if b.get("block_id", "").startswith("correction_")]
        assert len(correction_blocks) == 0

        # Should have a context block with correction info
        context_blocks = [b for b in blocks if b.get("type") == "context"]
        assert len(context_blocks) == 1
        text = context_blocks[0]["elements"][0]["text"]
        assert "Health & Vitality" in text
        assert "Mind & Growth" in text

    def test_reroutes_capture_to_correct_dimension_channel(self):
        mock_query = MagicMock(return_value=[{"message_text": "My health update"}])
        mock_execute = MagicMock(return_value=None)

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "run_async", side_effect=lambda c: c), \
             patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"}):

            ack = MagicMock()
            client = MagicMock()
            selected_value = {
                "ts": "ts123",
                "correct_dimension": "Health & Vitality",
                "original_dimensions": ["Mind & Growth"],
            }
            body = _make_body({}, selected_option_value=selected_value)

            handle_dimension_select(ack, body, client)

            client.chat_postMessage.assert_called_once()
            post_kwargs = client.chat_postMessage.call_args[1]
            assert post_kwargs["channel"] == "C_HEALTH"
            assert "My health update" in post_kwargs["text"]
            blocks = post_kwargs["blocks"]
            section_text = blocks[0]["text"]["text"]
            assert "corrected" in section_text.lower()

    @patch("handlers.commands._channel_ids", {})
    @patch("handlers.feedback.run_async")
    def test_missing_channel_id_skips_reroute(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": [],
        }
        body = _make_body({}, selected_option_value=selected_value)

        handle_dimension_select(ack, body, client)

        ack.assert_called_once()
        client.chat_postMessage.assert_not_called()

    def test_missing_classification_record_skips_reroute(self):
        mock_query = MagicMock(return_value=[])
        mock_execute = MagicMock(return_value=None)

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "run_async", side_effect=lambda c: c), \
             patch("handlers.commands._channel_ids", {"brain-systems": "C_SYS"}):

            ack = MagicMock()
            client = MagicMock()
            selected_value = {
                "ts": "ts_missing",
                "correct_dimension": "Systems & Environment",
                "original_dimensions": [],
            }
            body = _make_body({}, selected_option_value=selected_value)

            handle_dimension_select(ack, body, client)

            ack.assert_called_once()
            client.chat_postMessage.assert_not_called()

    def test_defaults_to_brain_systems_for_unknown_dimension(self):
        mock_query = MagicMock(return_value=[{"message_text": "test"}])
        mock_execute = MagicMock(return_value=None)

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "run_async", side_effect=lambda c: c), \
             patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"}):

            ack = MagicMock()
            client = MagicMock()
            selected_value = {
                "ts": "ts123",
                "correct_dimension": "Nonexistent Dimension",
                "original_dimensions": [],
            }
            body = _make_body({}, selected_option_value=selected_value)

            handle_dimension_select(ack, body, client)
            # Fallback is "brain-systems" but it's not in _channel_ids
            client.chat_postMessage.assert_not_called()

    @patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"})
    @patch("handlers.feedback.run_async")
    def test_missing_message_channel_skips_message_update(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": [],
        }
        body = _make_body({}, selected_option_value=selected_value)
        body["channel"] = {}
        body["message"] = {}

        handle_dimension_select(ack, body, client)

        ack.assert_called_once()
        client.chat_update.assert_not_called()

    @patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"})
    @patch("handlers.feedback.run_async", side_effect=Exception("DB crash"))
    def test_exception_does_not_propagate(self, mock_run_async):
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": [],
        }
        body = _make_body({}, selected_option_value=selected_value)

        handle_dimension_select(ack, body, client)
        ack.assert_called_once()

    @patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"})
    @patch("handlers.feedback.run_async")
    def test_correction_text_includes_was_dimensions(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": ["Wealth & Finance", "Relationships"],
        }
        body = _make_body({}, selected_option_value=selected_value)

        handle_dimension_select(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        assert call_kwargs["text"] == "Corrected to Health & Vitality"

    @patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"})
    @patch("handlers.feedback.run_async")
    def test_empty_original_dimensions_shows_none(self, mock_run_async):
        mock_run_async.return_value = None
        ack = MagicMock()
        client = MagicMock()
        selected_value = {
            "ts": "ts123",
            "correct_dimension": "Health & Vitality",
            "original_dimensions": [],
        }
        body = _make_body({}, selected_option_value=selected_value)

        handle_dimension_select(ack, body, client)

        call_kwargs = client.chat_update.call_args[1]
        blocks = call_kwargs["blocks"]
        context_blocks = [b for b in blocks if b.get("type") == "context"]
        text = context_blocks[0]["elements"][0]["text"]
        assert "none" in text

    def test_reroute_block_includes_feedback_context(self):
        mock_query = MagicMock(return_value=[{"message_text": "Weekly gym session"}])
        mock_execute = MagicMock(return_value=None)

        with patch.object(fb_mod, "query", mock_query), \
             patch.object(fb_mod, "execute", mock_execute), \
             patch.object(fb_mod, "run_async", side_effect=lambda c: c), \
             patch("handlers.commands._channel_ids", {"brain-health": "C_HEALTH"}):

            ack = MagicMock()
            client = MagicMock()
            selected_value = {
                "ts": "ts123",
                "correct_dimension": "Health & Vitality",
                "original_dimensions": ["Mind & Growth"],
            }
            body = _make_body({}, selected_option_value=selected_value)

            handle_dimension_select(ack, body, client)

            post_kwargs = client.chat_postMessage.call_args[1]
            blocks = post_kwargs["blocks"]
            context_blocks = [b for b in blocks if b.get("type") == "context"]
            assert len(context_blocks) == 1
            assert "feedback" in context_blocks[0]["elements"][0]["text"].lower()

"""Tests for progress feedback UX: ephemeral messages and progress_callback."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, call

import pytest

# ---------------------------------------------------------------------------
# Mock dependencies before importing modules under test
# ---------------------------------------------------------------------------
cfg_mock = sys.modules.setdefault("config", MagicMock())
cfg_mock.ANTHROPIC_API_KEY = "test-key"
cfg_mock.ANTHROPIC_MODEL = "claude-test"
cfg_mock.DB_PATH = Path("/tmp/test.db")
cfg_mock.VAULT_PATH = Path("/tmp/vault")
cfg_mock.COMMANDS_PATH = Path("/tmp/commands")
cfg_mock.CLAUDE_MD_PATH = Path("/tmp/CLAUDE.md")
cfg_mock.NOTION_REGISTRY_PATH = Path("/tmp/notion-registry.json")
cfg_mock.NOTION_TOKEN = ""
cfg_mock.NOTION_COLLECTIONS = {}
cfg_mock.DIMENSION_CHANNELS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}
cfg_mock.DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness"],
    "Wealth & Finance": ["money", "finance"],
    "Relationships": ["friend", "family"],
    "Mind & Growth": ["learn", "read"],
    "Purpose & Impact": ["career", "mission"],
    "Systems & Environment": ["system", "automate"],
}
cfg_mock.PROJECT_KEYWORDS = ["project", "milestone"]
cfg_mock.RESOURCE_KEYWORDS = ["article", "book"]
cfg_mock.OWNER_SLACK_ID = ""
cfg_mock.CONFIDENCE_THRESHOLD = 0.60
cfg_mock.BOUNCER_TIMEOUT_MINUTES = 15
cfg_mock.CLASSIFIER_LLM_MODEL = "claude-haiku-4-5-20251001"
cfg_mock.EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
cfg_mock.EMBEDDING_DIM = 384

sys.modules.setdefault("slack_bolt", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("core.db_connection", MagicMock())
sys.modules.setdefault("core.async_utils", MagicMock())
sys.modules.setdefault("core.formatter", MagicMock())
sys.modules.setdefault("core.notion_client", MagicMock())
sys.modules.setdefault("core.notion_sync", MagicMock())
sys.modules.setdefault("core.vault_ops", MagicMock())
sys.modules.setdefault("core.db_ops", MagicMock())
sys.modules.setdefault("core.output_parser", MagicMock())


# ---------------------------------------------------------------------------
# Tests for _run_ai_command progress feedback
# ---------------------------------------------------------------------------

class TestRunAiCommandProgress:
    """Test ephemeral progress messages in _run_ai_command."""

    def _make_mocks(self):
        """Create standard mocks for _run_ai_command."""
        client = MagicMock()

        # Mock the anthropic response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Test result")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        ai_client_instance = MagicMock()
        ai_client_instance.messages.create.return_value = mock_response

        return client, ai_client_instance, mock_response

    def test_three_ephemeral_messages_sent(self):
        """_run_ai_command calls chat_postEphemeral 3 times with trigger_channel_id."""
        client, ai_client_instance, mock_response = self._make_mocks()

        with patch("handlers.commands.run_async", return_value={"db": {}, "vault": {}, "notion": {}, "graph": {}}), \
             patch("handlers.commands.load_system_context", return_value="system"), \
             patch("handlers.commands.load_command_prompt", return_value="prompt"), \
             patch("handlers.commands.build_claude_messages", return_value=[{"role": "user", "content": "test"}]), \
             patch("handlers.commands.anthropic") as mock_anthropic, \
             patch("handlers.commands._write_command_output_to_vault"), \
             patch("handlers.commands._channel_ids", {"brain-daily": "C123"}):

            mock_anthropic.Anthropic.return_value = ai_client_instance

            from handlers.commands import _run_ai_command
            _run_ai_command(client, "U123", "today", "brain-daily", "", trigger_channel_id="C999")

        ephemeral_calls = client.chat_postEphemeral.call_args_list
        assert len(ephemeral_calls) == 3

        # Stage 1: Gathering context
        assert "Gathering context" in ephemeral_calls[0].kwargs.get("text", ephemeral_calls[0][1].get("text", ""))
        # Stage 2: Asking Claude
        assert "Asking Claude" in ephemeral_calls[1].kwargs.get("text", ephemeral_calls[1][1].get("text", ""))
        # Stage 3: Results posted
        assert "results posted" in ephemeral_calls[2].kwargs.get("text", ephemeral_calls[2][1].get("text", ""))

    def test_no_ephemeral_when_trigger_channel_none(self):
        """_run_ai_command sends no ephemeral messages when trigger_channel_id is None."""
        client, ai_client_instance, mock_response = self._make_mocks()

        with patch("handlers.commands.run_async", return_value={"db": {}, "vault": {}, "notion": {}, "graph": {}}), \
             patch("handlers.commands.load_system_context", return_value="system"), \
             patch("handlers.commands.load_command_prompt", return_value="prompt"), \
             patch("handlers.commands.build_claude_messages", return_value=[{"role": "user", "content": "test"}]), \
             patch("handlers.commands.anthropic") as mock_anthropic, \
             patch("handlers.commands._write_command_output_to_vault"), \
             patch("handlers.commands._channel_ids", {"brain-daily": "C123"}):

            mock_anthropic.Anthropic.return_value = ai_client_instance

            from handlers.commands import _run_ai_command
            _run_ai_command(client, "U123", "today", "brain-daily", "")

        client.chat_postEphemeral.assert_not_called()

    def test_ephemeral_exception_does_not_break_command(self):
        """_run_ai_command still works if chat_postEphemeral raises an exception."""
        client, ai_client_instance, mock_response = self._make_mocks()
        client.chat_postEphemeral.side_effect = Exception("Slack API error")

        with patch("handlers.commands.run_async", return_value={"db": {}, "vault": {}, "notion": {}, "graph": {}}), \
             patch("handlers.commands.load_system_context", return_value="system"), \
             patch("handlers.commands.load_command_prompt", return_value="prompt"), \
             patch("handlers.commands.build_claude_messages", return_value=[{"role": "user", "content": "test"}]), \
             patch("handlers.commands.anthropic") as mock_anthropic, \
             patch("handlers.commands._write_command_output_to_vault"), \
             patch("handlers.commands._channel_ids", {"brain-daily": "C123"}):

            mock_anthropic.Anthropic.return_value = ai_client_instance

            from handlers.commands import _run_ai_command
            # Should not raise
            _run_ai_command(client, "U123", "today", "brain-daily", "", trigger_channel_id="C999")

        # The main result should still be posted
        client.chat_postMessage.assert_called_once()

    def test_stage3_shows_dm_for_no_output_channel(self):
        """Stage 3 message says 'DM' when output_channel is None."""
        client, ai_client_instance, mock_response = self._make_mocks()
        client.conversations_open.return_value = {"channel": {"id": "D456"}}

        with patch("handlers.commands.run_async", return_value={"db": {}, "vault": {}, "notion": {}, "graph": {}}), \
             patch("handlers.commands.load_system_context", return_value="system"), \
             patch("handlers.commands.load_command_prompt", return_value="prompt"), \
             patch("handlers.commands.build_claude_messages", return_value=[{"role": "user", "content": "test"}]), \
             patch("handlers.commands.anthropic") as mock_anthropic, \
             patch("handlers.commands._write_command_output_to_vault"):

            mock_anthropic.Anthropic.return_value = ai_client_instance

            from handlers.commands import _run_ai_command
            _run_ai_command(client, "U123", "context-load", None, "", trigger_channel_id="C999")

        ephemeral_calls = client.chat_postEphemeral.call_args_list
        assert len(ephemeral_calls) == 3
        stage3_text = ephemeral_calls[2].kwargs.get("text", ephemeral_calls[2][1].get("text", ""))
        assert "DM" in stage3_text


# ---------------------------------------------------------------------------
# Tests for _make_handler passing trigger_channel_id
# ---------------------------------------------------------------------------

class TestMakeHandlerTriggerId:
    """Test that _make_handler passes trigger_channel_id from command."""

    def test_handler_passes_trigger_channel_id(self):
        """_make_handler extracts channel_id from command and passes it."""
        mock_executor = MagicMock()

        with patch("handlers.commands.executor", mock_executor):
            from handlers.commands import register

            # Access the _make_handler closure via register internals
            # We'll test by creating a mock App and checking executor.submit args
            mock_app = MagicMock()
            register(mock_app)

            # Find the handler registered for /brain-today
            handler_calls = mock_app.command.call_args_list
            brain_today_call = None
            for c in handler_calls:
                if c[0][0] == "/brain-today":
                    brain_today_call = c
                    break

            assert brain_today_call is not None, "No handler registered for /brain-today"

            # The handler is the argument to the decorator call
            # mock_app.command("/brain-today") returns a mock, which is called with the handler
            registered_handler = mock_app.command.return_value.call_args_list

            # Instead, let's directly test by calling the registered handler
            # Get the handler function that was passed
            mock_ack = MagicMock()
            mock_command = {"user_id": "U123", "text": "test input", "channel_id": "C555"}
            mock_client = MagicMock()

            # Since all handlers go through the same mock_app.command().return_value,
            # let's test _make_handler directly
            # Re-import to get at the internal function
            import handlers.commands as cmd_module

            # Access _make_handler through the module's register function
            # Actually we can just call _run_ai_command and check the args
            # Let's verify by checking executor.submit is called with trigger_channel_id

            # Reset and call via the last registered handler
            mock_executor.reset_mock()

            # Create a handler the same way _make_handler does
            # We need to call the function the way Slack Bolt would
            # The simplest approach: just verify _make_handler is defined correctly
            # by inspecting the source or testing the actual closure

            # Direct approach: create a handler and call it
            handler = None
            original_command = mock_app.command

            def capture_command(cmd_name):
                def decorator(fn):
                    nonlocal handler
                    if cmd_name == "/brain-today":
                        handler = fn
                    return fn
                return decorator

            mock_app2 = MagicMock()
            mock_app2.command = capture_command

            register(mock_app2)

            assert handler is not None, "Handler not captured"
            handler(mock_ack, mock_command, mock_client)

            mock_executor.submit.assert_called_once()
            submit_args = mock_executor.submit.call_args[0]
            # submit_args: (_run_ai_command, client, user_id, brain_command, output_channel, user_input, trigger_channel_id)
            assert submit_args[5] == "test input"  # user_input
            assert submit_args[6] == "C555"  # trigger_channel_id


# ---------------------------------------------------------------------------
# Tests for gather_command_context progress_callback
# ---------------------------------------------------------------------------

class TestGatherContextProgressCallback:
    """Test progress_callback parameter in gather_command_context."""

    def test_callback_called_at_key_points(self):
        """progress_callback is called with db_complete, vault_complete, graph_complete."""
        callback = MagicMock()

        mock_registry = MagicMock()
        mock_registry.exists.return_value = False

        with patch("core.context_loader.db_ops") as mock_db_ops, \
             patch("core.context_loader.vault_ops") as mock_vault_ops, \
             patch("core.context_loader.config") as mock_config:

            mock_config.DB_PATH = Path("/tmp/test.db")
            mock_config.VAULT_PATH = Path("/tmp/vault")
            mock_config.NOTION_REGISTRY_PATH = mock_registry
            mock_db_ops.query = AsyncMock(return_value=[])
            mock_vault_ops.read_file = MagicMock(return_value="")

            from core.context_loader import gather_command_context

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    gather_command_context("today", user_input="", progress_callback=callback)
                )
            finally:
                loop.close()

        callback.assert_any_call("db_complete")
        callback.assert_any_call("vault_complete")
        callback.assert_any_call("graph_complete")
        assert callback.call_count == 3

    def test_works_without_callback(self):
        """gather_command_context works fine with progress_callback=None (backward compat)."""
        mock_registry = MagicMock()
        mock_registry.exists.return_value = False

        with patch("core.context_loader.db_ops") as mock_db_ops, \
             patch("core.context_loader.vault_ops") as mock_vault_ops, \
             patch("core.context_loader.config") as mock_config:

            mock_config.DB_PATH = Path("/tmp/test.db")
            mock_config.VAULT_PATH = Path("/tmp/vault")
            mock_config.NOTION_REGISTRY_PATH = mock_registry
            mock_db_ops.query = AsyncMock(return_value=[])
            mock_vault_ops.read_file = MagicMock(return_value="")

            from core.context_loader import gather_command_context

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    gather_command_context("today", user_input="")
                )
            finally:
                loop.close()

        # Should return a valid context dict without errors
        assert "db" in result
        assert "vault" in result

    def test_callback_not_called_when_none(self):
        """No errors when progress_callback is not provided."""
        mock_registry = MagicMock()
        mock_registry.exists.return_value = False

        with patch("core.context_loader.db_ops") as mock_db_ops, \
             patch("core.context_loader.vault_ops") as mock_vault_ops, \
             patch("core.context_loader.config") as mock_config:

            mock_config.DB_PATH = Path("/tmp/test.db")
            mock_config.VAULT_PATH = Path("/tmp/vault")
            mock_config.NOTION_REGISTRY_PATH = mock_registry
            mock_db_ops.query = AsyncMock(return_value=[])
            mock_vault_ops.read_file = MagicMock(return_value="")

            from core.context_loader import gather_command_context

            loop = asyncio.new_event_loop()
            try:
                # Explicitly pass None
                result = loop.run_until_complete(
                    gather_command_context("today", user_input="", progress_callback=None)
                )
            finally:
                loop.close()

        assert isinstance(result, dict)

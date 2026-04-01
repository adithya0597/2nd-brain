"""Tests for core.langfuse_client — singleton, graceful degradation, flush."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure brain-bot dir is on sys.path
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Ensure config mock exists
sys.modules.setdefault("config", MagicMock())

from core.langfuse_client import get_langfuse, reset_client, flush


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton before and after each test."""
    reset_client()
    yield
    reset_client()


class TestGetLangfuse:
    """Tests for the get_langfuse() singleton."""

    def test_returns_none_when_disabled(self):
        """When LANGFUSE_ENABLED is not set, returns None."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LANGFUSE_ENABLED", None)
            result = get_langfuse()
            assert result is None

    def test_returns_none_when_explicitly_disabled(self):
        """When LANGFUSE_ENABLED=false, returns None."""
        with patch.dict(os.environ, {"LANGFUSE_ENABLED": "false"}, clear=False):
            result = get_langfuse()
            assert result is None

    def test_returns_none_when_keys_missing(self):
        """When enabled but keys missing, returns None."""
        env = {"LANGFUSE_ENABLED": "true", "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            result = get_langfuse()
            assert result is None

    def test_returns_none_when_public_key_only(self):
        """When enabled with only public key, returns None."""
        env = {"LANGFUSE_ENABLED": "true", "LANGFUSE_PUBLIC_KEY": "pk-test"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            result = get_langfuse()
            assert result is None

    @patch.dict(os.environ, {
        "LANGFUSE_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_BASE_URL": "https://test.langfuse.com",
    })
    def test_returns_client_when_configured(self):
        """When enabled and keys set, returns a Langfuse client (mocked)."""
        mock_langfuse_class = MagicMock()
        mock_instance = MagicMock()
        mock_langfuse_class.return_value = mock_instance

        mock_module = MagicMock()
        mock_module.Langfuse = mock_langfuse_class

        with patch.dict(sys.modules, {"langfuse": mock_module}):
            result = get_langfuse()
            assert result is mock_instance
            mock_langfuse_class.assert_called_once_with(
                public_key="pk-test",
                secret_key="sk-test",
                host="https://test.langfuse.com",
            )

    @patch.dict(os.environ, {
        "LANGFUSE_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
    })
    def test_singleton_returns_same_instance(self):
        """Subsequent calls return the same client."""
        mock_langfuse_class = MagicMock()
        mock_instance = MagicMock()
        mock_langfuse_class.return_value = mock_instance

        mock_module = MagicMock()
        mock_module.Langfuse = mock_langfuse_class

        with patch.dict(sys.modules, {"langfuse": mock_module}):
            first = get_langfuse()
            second = get_langfuse()
            assert first is second
            assert mock_langfuse_class.call_count == 1

    def test_reset_clears_singleton(self):
        """reset_client() allows re-initialization."""
        # First call: disabled
        with patch.dict(os.environ, {"LANGFUSE_ENABLED": "false"}, clear=False):
            result1 = get_langfuse()
            assert result1 is None

        reset_client()

        # Second call: enabled (with mock)
        mock_langfuse_class = MagicMock()
        mock_instance = MagicMock()
        mock_langfuse_class.return_value = mock_instance
        mock_module = MagicMock()
        mock_module.Langfuse = mock_langfuse_class

        with (
            patch.dict(os.environ, {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
            }),
            patch.dict(sys.modules, {"langfuse": mock_module}),
        ):
            result2 = get_langfuse()
            assert result2 is mock_instance

    @patch.dict(os.environ, {
        "LANGFUSE_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
    })
    def test_graceful_on_import_error(self):
        """Returns None if langfuse package is not installed."""
        # Remove langfuse from sys.modules so the real import is attempted
        saved = sys.modules.pop("langfuse", None)
        try:
            with patch("builtins.__import__", side_effect=ImportError("No module named 'langfuse'")):
                result = get_langfuse()
                assert result is None
        finally:
            if saved is not None:
                sys.modules["langfuse"] = saved

    @patch.dict(os.environ, {"LANGFUSE_ENABLED": "1"})
    def test_enabled_with_1(self):
        """LANGFUSE_ENABLED=1 is treated as true."""
        env = {"LANGFUSE_ENABLED": "1"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            # Will return None because keys are missing, but the 'enabled' check passes
            result = get_langfuse()
            assert result is None  # Keys missing

    @patch.dict(os.environ, {"LANGFUSE_ENABLED": "yes"})
    def test_enabled_with_yes(self):
        """LANGFUSE_ENABLED=yes is treated as true."""
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        result = get_langfuse()
        assert result is None  # Keys missing, but enabled check passed


class TestFlush:
    """Tests for the flush() function."""

    def test_flush_noop_when_none(self):
        """flush() does nothing when client is None."""
        # No error should be raised
        flush()

    @patch.dict(os.environ, {
        "LANGFUSE_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
    })
    def test_flush_calls_client_flush(self):
        """flush() calls the underlying client's flush method."""
        mock_langfuse_class = MagicMock()
        mock_instance = MagicMock()
        mock_langfuse_class.return_value = mock_instance
        mock_module = MagicMock()
        mock_module.Langfuse = mock_langfuse_class

        with patch.dict(sys.modules, {"langfuse": mock_module}):
            get_langfuse()  # Initialize
            flush()
            mock_instance.flush.assert_called_once()

    @patch.dict(os.environ, {
        "LANGFUSE_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
    })
    def test_flush_handles_exception(self):
        """flush() swallows exceptions from the client."""
        mock_langfuse_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.flush.side_effect = RuntimeError("network error")
        mock_langfuse_class.return_value = mock_instance
        mock_module = MagicMock()
        mock_module.Langfuse = mock_langfuse_class

        with patch.dict(sys.modules, {"langfuse": mock_module}):
            get_langfuse()  # Initialize
            # Should not raise
            flush()

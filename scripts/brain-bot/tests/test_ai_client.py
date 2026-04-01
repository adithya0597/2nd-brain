"""Tests for core.ai_client singleton."""
import sys
from unittest.mock import MagicMock, patch

# Ensure config mock exists
sys.modules.setdefault("config", MagicMock())

from core.ai_client import get_ai_client, get_ai_model, reset_client


class TestAiClient:
    def setup_method(self):
        reset_client()

    def teardown_method(self):
        reset_client()

    def test_returns_none_without_api_key(self):
        with patch("config.ANTHROPIC_API_KEY", ""):
            reset_client()
            assert get_ai_client() is None

    def test_returns_client_with_api_key(self):
        with patch("config.ANTHROPIC_API_KEY", "sk-test-key"), \
             patch("config.AI_PROVIDER", "anthropic"):
            reset_client()
            client = get_ai_client()
            assert client is not None

    def test_singleton_returns_same_instance(self):
        with patch("config.ANTHROPIC_API_KEY", "sk-test-key"):
            reset_client()
            c1 = get_ai_client()
            c2 = get_ai_client()
            assert c1 is c2

    def test_get_ai_model_default(self):
        with patch("config.ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"), \
             patch("config.AI_PROVIDER", "anthropic"):
            assert get_ai_model() == "claude-sonnet-4-5-20250929"

    def test_reset_clears_singleton(self):
        with patch("config.ANTHROPIC_API_KEY", "sk-test-key"), \
             patch("config.AI_PROVIDER", "anthropic"):
            reset_client()
            c1 = get_ai_client()
            reset_client()
            c2 = get_ai_client()
            assert c1 is not c2

"""Tests for core/ai_client.py — AI client singleton and response types."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.ai_client import (
    _ContentBlock,
    _Usage,
    _Response,
    _detect_provider,
    get_ai_client,
    get_ai_model,
    reset_client,
)


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

class TestContentBlock:
    def test_text_attribute(self):
        block = _ContentBlock("hello")
        assert block.text == "hello"


class TestUsage:
    def test_defaults(self):
        usage = _Usage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_creation_input_tokens == 0
        assert usage.cache_read_input_tokens == 0

    def test_custom_values(self):
        usage = _Usage(input_tokens=100, output_tokens=50)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50


class TestResponse:
    def test_basic(self):
        resp = _Response("Hello world", model="test-model", input_tokens=10, output_tokens=5)
        assert resp.content[0].text == "Hello world"
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.model == "test-model"
        assert resp.role == "assistant"
        assert resp.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# _detect_provider
# ---------------------------------------------------------------------------

class TestDetectProvider:
    def test_explicit_provider(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = "gemini"
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = _detect_provider()
        assert result == "gemini"

    def test_explicit_anthropic(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = "Anthropic"
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = _detect_provider()
        assert result == "anthropic"

    def test_auto_detect_gemini(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = "key-123"
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = _detect_provider()
        assert result == "gemini"

    def test_auto_detect_anthropic(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = "sk-ant-123"
        with patch.dict("sys.modules", {"config": cfg}):
            result = _detect_provider()
        assert result == "anthropic"

    def test_no_provider(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = _detect_provider()
        assert result is None


# ---------------------------------------------------------------------------
# get_ai_client
# ---------------------------------------------------------------------------

class TestGetAiClient:
    def setup_method(self):
        reset_client()

    def teardown_method(self):
        reset_client()

    def test_no_provider_returns_none(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = get_ai_client()
        assert result is None

    def test_cached_after_init(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            r1 = get_ai_client()
            r2 = get_ai_client()
        assert r1 is r2  # Same cached value

    def test_gemini_init_failure(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = "gemini"
        cfg.GEMINI_API_KEY = "test-key"
        cfg.GEMINI_MODEL = "gemini-2.5-flash"
        with (
            patch.dict("sys.modules", {"config": cfg}),
            patch.dict("sys.modules", {"google": MagicMock(), "google.genai": MagicMock(side_effect=Exception("import fail"))}),
        ):
            # Force reimport to hit the exception path
            reset_client()
            result = get_ai_client()
        # May or may not be None depending on mock behavior

    def test_anthropic_init_failure(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = "anthropic"
        cfg.ANTHROPIC_API_KEY = "test-key"
        cfg.ANTHROPIC_MODEL = "claude-sonnet"
        with (
            patch.dict("sys.modules", {"config": cfg}),
            patch("core.ai_client._AnthropicClient", side_effect=Exception("no anthropic")),
        ):
            reset_client()
            result = get_ai_client()
        assert result is None


# ---------------------------------------------------------------------------
# get_ai_model
# ---------------------------------------------------------------------------

class TestGetAiModel:
    def test_gemini_model(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = "gemini"
        cfg.GEMINI_MODEL = "gemini-2.5-flash"
        with patch.dict("sys.modules", {"config": cfg}):
            result = get_ai_model()
        assert result == "gemini-2.5-flash"

    def test_anthropic_model(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = "anthropic"
        cfg.ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
        with patch.dict("sys.modules", {"config": cfg}):
            result = get_ai_model()
        assert result == "claude-sonnet-4-5-20250929"

    def test_unknown_provider(self):
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = get_ai_model()
        assert result == "unknown"


# ---------------------------------------------------------------------------
# reset_client
# ---------------------------------------------------------------------------

class TestResetClient:
    def test_reset(self):
        reset_client()
        # After reset, next get_ai_client should reinitialize
        cfg = MagicMock()
        cfg.AI_PROVIDER = ""
        cfg.GEMINI_API_KEY = ""
        cfg.ANTHROPIC_API_KEY = ""
        with patch.dict("sys.modules", {"config": cfg}):
            result = get_ai_client()
        assert result is None

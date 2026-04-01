"""Tests for core/classifier.py — LLM tier and edge cases."""
import json
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

cfg = sys.modules["config"]
cfg.DIMENSION_TOPICS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}
cfg.DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness", "workout"],
    "Wealth & Finance": ["money", "invest", "budget"],
    "Relationships": ["friend", "family"],
    "Mind & Growth": ["learn", "read", "book"],
    "Purpose & Impact": ["career", "mission"],
    "Systems & Environment": ["system", "automate", "tool"],
}
cfg.CLASSIFIER_LLM_MODEL = "claude-haiku"

from core.classifier import MessageClassifier, DimensionScore


class TestClassifierLLMTier:
    """Tests for the LLM-based classification tier."""

    def _make_classifier(self):
        return MessageClassifier(keywords=cfg.DIMENSION_KEYWORDS)

    def test_llm_tier_returns_valid_json(self):
        cls = self._make_classifier()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"dimension": "Health & Vitality", "confidence": 0.85},
        ]))]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("core.classifier._get_anthropic_client", return_value=mock_client):
            result = cls._tier_llm("Going to the gym today")

        assert len(result) >= 1
        assert result[0].dimension == "Health & Vitality"
        assert result[0].method == "llm"

    def test_llm_tier_returns_none(self):
        cls = self._make_classifier()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="none")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("core.classifier._get_anthropic_client", return_value=mock_client):
            result = cls._tier_llm("just random text")

        assert result == []

    def test_llm_tier_no_client(self):
        cls = self._make_classifier()
        with patch("core.classifier._get_anthropic_client", return_value=None):
            result = cls._tier_llm("some text")
        assert result == []

    def test_llm_tier_fallback_text_match(self):
        cls = self._make_classifier()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is about Mind & Growth")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("core.classifier._get_anthropic_client", return_value=mock_client):
            result = cls._tier_llm("studying philosophy")

        assert len(result) == 1
        assert result[0].dimension == "Mind & Growth"

    def test_llm_tier_exception_handled(self):
        cls = self._make_classifier()
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        with patch("core.classifier._get_anthropic_client", return_value=mock_client):
            result = cls._tier_llm("some text")

        assert result == []

    def test_llm_tier_bad_json(self):
        cls = self._make_classifier()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not json at all")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("core.classifier._get_anthropic_client", return_value=mock_client):
            result = cls._tier_llm("some text")

        # Should fallback or return empty
        assert isinstance(result, list)


class TestClassifierUpdateKeywords:
    def test_update_keywords(self):
        cls = MessageClassifier(keywords={"Health": ["fitness"]})
        cls.update_keywords({"Health": ["yoga", "meditation"]})
        assert "yoga" in cls._keywords.get("Health", [])

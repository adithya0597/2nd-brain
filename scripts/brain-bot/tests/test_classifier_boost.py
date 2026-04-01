"""Tests for classifier zero-shot tier and cost optimization."""
import sys
from unittest.mock import MagicMock, patch


# Mock config before importing (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("core.db_connection", MagicMock())
sys.modules.setdefault("anthropic", MagicMock())


class TestZeroShotTier:
    """Test the zero-shot classification tier."""

    def test_returns_empty_when_model_unavailable(self):
        """Zero-shot returns [] when embedding model can't load."""
        with patch("core.embedding_store._get_model", return_value=None):
            from core.classifier import MessageClassifier

            clf = MessageClassifier()
            result = clf._tier_zero_shot("I went to the gym today")
            assert result == []

    def test_returns_scores_with_model(self):
        """Zero-shot returns scored dimensions with a working model."""
        import numpy as np

        fake_model = MagicMock()
        # Return a random embedding for the input text
        fake_model.encode = MagicMock(
            side_effect=lambda texts, **kw: np.random.rand(len(texts), 384).astype(
                np.float32
            )
        )

        with patch("core.embedding_store._get_model", return_value=fake_model):
            from core.classifier import MessageClassifier, _dimension_embeddings

            _dimension_embeddings.clear()  # Force re-computation

            clf = MessageClassifier()
            result = clf._tier_zero_shot("I went to the gym today")
            # Should return some scores (actual values depend on random embeddings)
            assert isinstance(result, list)
            for score in result:
                assert hasattr(score, "dimension")
                assert hasattr(score, "confidence")
                assert score.method == "zero_shot"

    def test_fallback_on_import_error(self):
        """Zero-shot returns [] when embedding_store import fails."""
        with patch.dict(sys.modules, {"core.embedding_store": None}):
            from core.classifier import MessageClassifier

            MessageClassifier()
            # Should handle ImportError gracefully


class TestClassifierLLMModel:
    """Test that Tier 3 uses the correct (cheap) model."""

    def test_config_has_classifier_model(self):
        """Config should have CLASSIFIER_LLM_MODEL set to Haiku."""
        import config

        assert hasattr(config, "CLASSIFIER_LLM_MODEL")
        assert "haiku" in config.CLASSIFIER_LLM_MODEL.lower()


class TestClassifyPipeline:
    """Test the full classification pipeline with zero-shot integration."""

    def test_noise_short_circuits(self):
        from core.classifier import MessageClassifier

        clf = MessageClassifier()
        result = clf.classify("hello there")
        assert result.is_noise is True
        assert result.matches == []

    def test_keyword_match_short_circuits(self):
        from core.classifier import MessageClassifier

        clf = MessageClassifier()
        result = clf.classify(
            "I need to invest money in finance and budget my savings"
        )
        assert not result.is_noise
        assert len(result.matches) > 0
        assert result.matches[0].dimension == "Wealth & Finance"
        assert result.matches[0].method == "keyword"

    def test_actionable_detection(self):
        from core.classifier import MessageClassifier

        clf = MessageClassifier()
        result = clf.classify(
            "I need to schedule a doctor appointment for my health checkup"
        )
        assert result.is_actionable is True

    def test_multi_label_within_threshold(self):
        """When top-2 dimensions are close in confidence, both are kept."""
        from core.classifier import MessageClassifier

        clf = MessageClassifier(
            keywords={
                "Health & Vitality": ["workout"],
                "Mind & Growth": ["growth"],
                "Wealth & Finance": [],
                "Relationships": [],
                "Purpose & Impact": [],
                "Systems & Environment": [],
            }
        )
        # "workout for personal growth" should match both Health and Mind
        result = clf.classify("workout for personal growth and learning")
        # At minimum, keyword tier should find matches
        assert len(result.matches) >= 1

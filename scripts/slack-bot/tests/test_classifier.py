"""Tests for core/classifier.py — 4-tier hybrid message classification."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure slack-bot is on sys.path (conftest handles this, but be explicit)
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing classifier (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())
import config  # noqa: E402 — conftest populates all attributes

# Now import — classifier will see our mock config
from core.classifier import (
    MessageClassifier,
    ClassificationResult,
    DimensionScore,
    _NOISE_PATTERNS,
    _ACTION_PATTERNS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def classifier():
    """Return a MessageClassifier with the standard keyword set."""
    return MessageClassifier(keywords=dict(config.DIMENSION_KEYWORDS))


# ---------------------------------------------------------------------------
# Tier 0: Noise filter
# ---------------------------------------------------------------------------

class TestNoiseFilter:
    """Tests for noise detection (tier 0)."""

    @pytest.mark.parametrize("text", [
        "hello",
        "Hello!",
        "hi there",
        "hey",
        "thanks",
        "thank you",
        "gm",
        "gn",
        "ok",
        "okay",
        "cool",
        "nice",
        "great",
        "sure",
        "yep",
        "yup",
        "nope",
        "bye",
        "later",
        "cheers",
        "lol",
        "haha",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
        "what's up",
        "whats up",
        "how's it going",
        "how are you",
        "sup",
        "yo",
    ])
    def test_noise_messages_detected(self, classifier, text):
        result = classifier.classify(text)
        assert result.is_noise is True, f"'{text}' should be noise"
        assert result.matches == []

    @pytest.mark.parametrize("text", [
        "I need to exercise more",
        "Just finished a great workout at the gym",
        "Need to review my budget this week",
        "Meeting with family tomorrow",
        "I want to learn Python",
        "Setting up a new workflow",
        "hello I need to buy groceries",
    ])
    def test_non_noise_messages(self, classifier, text):
        result = classifier.classify(text)
        assert result.is_noise is False, f"'{text}' should NOT be noise"


# ---------------------------------------------------------------------------
# Tier 1: Keyword matching
# ---------------------------------------------------------------------------

class TestKeywordMatching:
    """Tests for keyword-based dimension classification (tier 1)."""

    def test_health_keywords(self, classifier):
        result = classifier.classify("I need to get to the gym and do a workout today")
        assert result.is_noise is False
        assert len(result.matches) > 0
        dims = [m.dimension for m in result.matches]
        assert "Health & Vitality" in dims

    def test_finance_keywords(self, classifier):
        result = classifier.classify("I should review my budget and check my savings account")
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Wealth & Finance" in dims

    def test_relationship_keywords(self, classifier):
        result = classifier.classify("Catching up with a friend for dinner tonight")
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Relationships" in dims

    def test_growth_keywords(self, classifier):
        result = classifier.classify("I want to learn more about philosophy and read a new book")
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Mind & Growth" in dims

    def test_purpose_keywords(self, classifier):
        result = classifier.classify("Working on my career and thinking about my mission in life")
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Purpose & Impact" in dims

    def test_systems_keywords(self, classifier):
        result = classifier.classify("Need to organize my workspace and set up a new workflow")
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Systems & Environment" in dims

    def test_multi_dimension_match(self, classifier):
        """A message mentioning keywords from multiple dimensions should match multiple."""
        result = classifier.classify(
            "I need to exercise more and also review my budget"
        )
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Health & Vitality" in dims
        assert "Wealth & Finance" in dims

    def test_keyword_method_label(self, classifier):
        result = classifier.classify("Going to the gym for a workout and some running")
        assert result.is_noise is False
        for match in result.matches:
            if match.dimension == "Health & Vitality":
                assert match.method == "keyword"

    def test_confidence_increases_with_more_keywords(self, classifier):
        """More keyword hits should yield higher confidence."""
        single = classifier.classify("gym")
        multi = classifier.classify("gym workout exercise running yoga")
        assert single.is_noise is False
        assert multi.is_noise is False

        single_health = [m for m in single.matches if m.dimension == "Health & Vitality"]
        multi_health = [m for m in multi.matches if m.dimension == "Health & Vitality"]
        assert len(single_health) > 0
        assert len(multi_health) > 0
        assert multi_health[0].confidence >= single_health[0].confidence

    def test_no_match_random_text(self, classifier):
        """Text with no dimension keywords should have no keyword matches
        (may fall through to embedding/LLM tiers which are not loaded in tests)."""
        result = classifier.classify("The weather is quite pleasant today with clear skies")
        assert result.is_noise is False
        # With no embedding model and no LLM key, we expect empty matches
        # (tiers 2 and 3 gracefully return [])
        keyword_matches = [m for m in result.matches if m.method == "keyword"]
        assert len(keyword_matches) == 0


# ---------------------------------------------------------------------------
# Action detection
# ---------------------------------------------------------------------------

class TestActionDetection:
    """Tests for the is_actionable flag."""

    @pytest.mark.parametrize("text", [
        "I need to exercise more",
        "Should call the dentist tomorrow",
        "Must finish the report by Friday",
        "todo: buy groceries",
        "Reminder to send the email",
        "Deadline for the project is next week",
        "Need to follow up with the team",
        "Schedule a meeting for Monday",
        "Book a flight for next month",
        "Call the insurance company",
        "Email the proposal to client",
        "Buy a new laptop charger",
        "Pay the electricity bill",
        "Submit the application before noon",
        "Send the invoice to accounting",
    ])
    def test_actionable_messages(self, classifier, text):
        result = classifier.classify(text)
        assert result.is_actionable is True, f"'{text}' should be actionable"

    @pytest.mark.parametrize("text", [
        "Had a great day at the park",
        "The sunset was beautiful",
        "Thinking about life lately",
        "Just finished watching a movie",
    ])
    def test_non_actionable_messages(self, classifier, text):
        result = classifier.classify(text)
        assert result.is_actionable is False, f"'{text}' should NOT be actionable"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for graceful handling of edge-case inputs."""

    def test_empty_string(self, classifier):
        result = classifier.classify("")
        # Empty matches noise regex (it matches ^...$ with optional whitespace)
        assert isinstance(result, ClassificationResult)

    def test_whitespace_only(self, classifier):
        result = classifier.classify("   ")
        assert isinstance(result, ClassificationResult)

    def test_very_long_message(self, classifier):
        text = "gym " * 5000
        result = classifier.classify(text)
        assert isinstance(result, ClassificationResult)
        assert result.is_noise is False

    def test_special_characters(self, classifier):
        text = "!@#$%^&*() workout <script>alert('xss')</script>"
        result = classifier.classify(text)
        assert isinstance(result, ClassificationResult)
        dims = [m.dimension for m in result.matches]
        assert "Health & Vitality" in dims

    def test_execution_time_tracked(self, classifier):
        result = classifier.classify("I need to exercise more")
        assert result.execution_time_ms >= 0

    def test_classify_returns_classification_result(self, classifier):
        result = classifier.classify("anything")
        assert isinstance(result, ClassificationResult)
        assert isinstance(result.matches, list)
        assert isinstance(result.is_noise, bool)
        assert isinstance(result.is_actionable, bool)
        assert isinstance(result.execution_time_ms, float)


# ---------------------------------------------------------------------------
# Merge scores helper
# ---------------------------------------------------------------------------

class TestMergeScores:
    """Tests for the static _merge_scores helper."""

    def test_merge_empty_lists(self):
        result = MessageClassifier._merge_scores([], [])
        assert result == []

    def test_merge_with_none(self):
        scores = [DimensionScore("Health & Vitality", 0.8, "keyword")]
        result = MessageClassifier._merge_scores(scores, None)
        assert len(result) == 1

    def test_merge_keeps_highest_confidence(self):
        a = [DimensionScore("Health & Vitality", 0.6, "keyword")]
        b = [DimensionScore("Health & Vitality", 0.9, "embedding")]
        result = MessageClassifier._merge_scores(a, b)
        assert len(result) == 1
        assert result[0].confidence == 0.9
        assert result[0].method == "embedding"

    def test_merge_combines_different_dimensions(self):
        a = [DimensionScore("Health & Vitality", 0.8, "keyword")]
        b = [DimensionScore("Wealth & Finance", 0.7, "embedding")]
        result = MessageClassifier._merge_scores(a, b)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Custom keyword dict
# ---------------------------------------------------------------------------

class TestCustomKeywords:
    """Test that custom keyword dictionaries work."""

    def test_custom_keywords(self):
        custom = {"Custom Dimension": ["foobar", "bazqux"]}
        clf = MessageClassifier(keywords=custom)
        result = clf.classify("this message contains foobar and bazqux")
        assert result.is_noise is False
        dims = [m.dimension for m in result.matches]
        assert "Custom Dimension" in dims

    def test_update_keywords(self):
        clf = MessageClassifier(keywords={"A": ["alpha"]})
        result = clf.classify("alpha is here")
        assert [m.dimension for m in result.matches] == ["A"]

        clf.update_keywords({"B": ["beta"]})
        result = clf.classify("beta is here")
        assert [m.dimension for m in result.matches] == ["B"]

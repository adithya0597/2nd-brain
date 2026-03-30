"""Integration tests for Langfuse instrumentation across modules.

Tests that Langfuse trace/generation/span/score calls are made correctly
when Langfuse is enabled, and that everything degrades gracefully when disabled.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure brain-bot dir is on sys.path
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Ensure config mock exists
sys.modules.setdefault("config", MagicMock())


@pytest.fixture
def mock_langfuse():
    """Provide a mock Langfuse client injected via get_langfuse."""
    lf = MagicMock()
    lf.trace = MagicMock()
    lf.generation = MagicMock()
    lf.span = MagicMock()
    lf.score = MagicMock()
    with patch("core.langfuse_client.get_langfuse", return_value=lf):
        yield lf


@pytest.fixture
def mock_langfuse_disabled():
    """Simulate Langfuse being disabled (returns None)."""
    with patch("core.langfuse_client.get_langfuse", return_value=None):
        yield


@pytest.mark.skip(reason="generate_text_sync and Langfuse instrumentation not yet implemented")
class TestAiClientLangfuse:
    """Tests for Langfuse instrumentation in ai_client.py."""

    def test_generation_logged_on_sync_call(self, mock_langfuse):
        """generate_text_sync logs a Langfuse generation when trace_metadata is provided."""
        # Mock the Gemini client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "test output"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=10,
            candidates_token_count=20,
        )
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("core.ai_client.get_ai_client", return_value=mock_client),
            patch("core.ai_client.get_ai_model", return_value="gemini-2.5-flash"),
        ):
            from core.ai_client import generate_text_sync
            text, resp = generate_text_sync(
                system="test system",
                messages=[{"role": "user", "content": "hello"}],
                trace_metadata={"caller": "test_caller"},
            )

        assert text == "test output"
        mock_langfuse.generation.assert_called_once()
        call_kwargs = mock_langfuse.generation.call_args
        assert call_kwargs.kwargs["name"] == "test_caller"
        assert call_kwargs.kwargs["model"] == "gemini-2.5-flash"

    def test_no_generation_when_disabled(self, mock_langfuse_disabled):
        """generate_text_sync works without errors when Langfuse is disabled."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "test"
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("core.ai_client.get_ai_client", return_value=mock_client),
            patch("core.ai_client.get_ai_model", return_value="gemini-2.5-flash"),
        ):
            from core.ai_client import generate_text_sync
            text, resp = generate_text_sync(
                system="test",
                messages=[{"role": "user", "content": "hi"}],
                trace_metadata={"caller": "test"},
            )
        assert text == "test"

    def test_generation_default_name_without_metadata(self, mock_langfuse):
        """Without trace_metadata, generation name defaults to 'generate_text'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "output"
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("core.ai_client.get_ai_client", return_value=mock_client),
            patch("core.ai_client.get_ai_model", return_value="gemini-2.5-pro"),
        ):
            from core.ai_client import generate_text_sync
            generate_text_sync(
                system="sys",
                messages=[{"role": "user", "content": "q"}],
            )

        mock_langfuse.generation.assert_called_once()
        assert mock_langfuse.generation.call_args.kwargs["name"] == "generate_text"


@pytest.mark.skip(reason="generate_text_sync and Langfuse instrumentation not yet implemented")
class TestClassifierLangfuse:
    """Tests for trace_metadata passthrough in classifier._tier_llm."""

    def test_classifier_passes_metadata(self, mock_langfuse):
        """_tier_llm passes trace_metadata to generate_text_sync."""
        with patch("core.ai_client.generate_text_sync") as mock_gen:
            mock_gen.return_value = ('none', MagicMock())

            from core.classifier import MessageClassifier
            c = MessageClassifier()
            c._tier_llm("test message about finances")

            mock_gen.assert_called_once()
            call_kwargs = mock_gen.call_args
            assert call_kwargs.kwargs.get("trace_metadata") == {"caller": "classifier_tier3"}


@pytest.mark.skip(reason="Langfuse span instrumentation not yet wired in search.py")
class TestSearchLangfuse:
    """Tests for Langfuse span in hybrid_search."""

    def test_search_creates_span(self, mock_langfuse):
        """hybrid_search creates a Langfuse span with timing info."""
        # Mock all search channels to return empty (so we test the span logging)
        with (
            patch("core.search._search_vector", return_value=[]),
            patch("core.search._search_chunks", return_value=[]),
            patch("core.search._search_fts", return_value=[]),
            patch("core.search._search_graph", return_value=[]),
        ):
            from core.search import hybrid_search
            response = hybrid_search("test query")

        mock_langfuse.span.assert_called_once()
        call_kwargs = mock_langfuse.span.call_args.kwargs
        assert call_kwargs["name"] == "hybrid_search"
        assert "query" in call_kwargs["input"]
        assert "elapsed_ms" in call_kwargs["metadata"]

    def test_search_works_when_disabled(self, mock_langfuse_disabled):
        """hybrid_search works normally when Langfuse is disabled."""
        with (
            patch("core.search._search_vector", return_value=[]),
            patch("core.search._search_chunks", return_value=[]),
            patch("core.search._search_fts", return_value=[]),
            patch("core.search._search_graph", return_value=[]),
        ):
            from core.search import hybrid_search
            response = hybrid_search("test query")

        assert response.results == []
        assert response.query == "test query"


@pytest.mark.skip(reason="generate_text_sync and Langfuse instrumentation not yet implemented")
class TestGracefulDegradation:
    """Tests that all Langfuse integration points degrade gracefully."""

    def test_ai_client_survives_langfuse_exception(self):
        """generate_text_sync works even if Langfuse raises."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        def broken_langfuse():
            raise RuntimeError("Langfuse broken")

        with (
            patch("core.ai_client.get_ai_client", return_value=mock_client),
            patch("core.ai_client.get_ai_model", return_value="gemini-2.5-flash"),
            patch("core.langfuse_client.get_langfuse", side_effect=broken_langfuse),
        ):
            from core.ai_client import generate_text_sync
            text, _ = generate_text_sync(
                system="s",
                messages=[{"role": "user", "content": "q"}],
                trace_metadata={"caller": "test"},
            )
        assert text == "ok"

    def test_search_survives_langfuse_exception(self):
        """hybrid_search works even if Langfuse span creation raises."""
        def broken_langfuse():
            raise RuntimeError("Langfuse broken")

        with (
            patch("core.search._search_vector", return_value=[]),
            patch("core.search._search_chunks", return_value=[]),
            patch("core.search._search_fts", return_value=[]),
            patch("core.search._search_graph", return_value=[]),
            patch("core.langfuse_client.get_langfuse", side_effect=broken_langfuse),
        ):
            from core.search import hybrid_search
            response = hybrid_search("test query")

        assert response.results == []

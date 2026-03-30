"""Tests for core.content_extractor — structured knowledge extraction."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())

from core.content_extractor import (
    ExtractionResult,
    ExtractedActionItem,
    ExtractedClaim,
    ExtractedFramework,
    _ensure_concept_stubs,
    _parse_extraction_json,
    _strip_code_fences,
    extract_knowledge,
    _MIN_CONTENT_LENGTH,
    _MAX_CONTENT_LENGTH,
)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_VALID_JSON = {
    "summary": "This article discusses effective habits for productivity.",
    "claims": [
        {"text": "Morning routines improve focus.", "confidence": "high", "source_context": "Studies show..."},
        {"text": "Cold showers boost energy.", "confidence": "medium", "source_context": "Anecdotal evidence..."},
    ],
    "frameworks": [
        {"name": "GTD", "description": "Getting Things Done methodology."},
    ],
    "action_items": [
        {"description": "Create a morning routine checklist.", "context": "From the habits section."},
        {"description": "Try cold showers for one week.", "context": "Energy experiment."},
    ],
    "key_concepts": ["Morning Routine", "Productivity", "Cold Showers"],
}

_EMPTY_ARRAYS_JSON = {
    "summary": "Short article with no actionable content.",
    "claims": [],
    "frameworks": [],
    "action_items": [],
    "key_concepts": [],
}

_ARTICLE_TEXT = "A" * 500  # Just long enough to pass min length check


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------


class TestStripCodeFences:
    def test_strips_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert _strip_code_fences(raw) == '{"key": "value"}'

    def test_strips_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert _strip_code_fences(raw) == '{"key": "value"}'

    def test_leaves_plain_json_untouched(self):
        raw = '{"key": "value"}'
        assert _strip_code_fences(raw) == '{"key": "value"}'


# ---------------------------------------------------------------------------
# _parse_extraction_json
# ---------------------------------------------------------------------------


class TestParseExtractionJson:
    def test_parses_all_fields(self):
        result = _parse_extraction_json(_VALID_JSON)

        assert result.summary == "This article discusses effective habits for productivity."
        assert len(result.claims) == 2
        assert result.claims[0].text == "Morning routines improve focus."
        assert result.claims[0].confidence == "high"
        assert result.claims[0].source_context == "Studies show..."
        assert result.claims[1].confidence == "medium"

        assert len(result.frameworks) == 1
        assert result.frameworks[0].name == "GTD"
        assert result.frameworks[0].description == "Getting Things Done methodology."

        assert len(result.action_items) == 2
        assert result.action_items[0].description == "Create a morning routine checklist."
        assert result.action_items[0].context == "From the habits section."

        assert result.key_concepts == ["Morning Routine", "Productivity", "Cold Showers"]
        assert result.raw_json == _VALID_JSON

    def test_handles_empty_arrays(self):
        result = _parse_extraction_json(_EMPTY_ARRAYS_JSON)

        assert result.summary == "Short article with no actionable content."
        assert result.claims == []
        assert result.frameworks == []
        assert result.action_items == []
        assert result.key_concepts == []

    def test_handles_missing_fields(self):
        result = _parse_extraction_json({"summary": "Just a summary."})

        assert result.summary == "Just a summary."
        assert result.claims == []
        assert result.frameworks == []
        assert result.action_items == []
        assert result.key_concepts == []

    def test_skips_invalid_claim_entries(self):
        raw = {
            "claims": [
                {"text": "Valid claim.", "confidence": "high"},
                "not a dict",
                {"no_text_field": True},
            ],
        }
        result = _parse_extraction_json(raw)
        assert len(result.claims) == 1
        assert result.claims[0].text == "Valid claim."

    def test_skips_non_string_concepts(self):
        raw = {"key_concepts": ["Valid", 42, None, "Also Valid"]}
        result = _parse_extraction_json(raw)
        assert result.key_concepts == ["Valid", "Also Valid"]


# ---------------------------------------------------------------------------
# extract_knowledge
# ---------------------------------------------------------------------------


class TestExtractKnowledge:
    """Tests for the async extract_knowledge function.

    Because extract_knowledge uses local imports (from core.ai_client import ...),
    we must patch at the source module, not on core.content_extractor.
    """

    @pytest.mark.asyncio
    async def test_returns_none_on_short_input(self):
        short_text = "Too short."
        result = await extract_knowledge(short_text, title="T", url="http://x")
        assert result is None

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_truncates_long_input(self):
        """Verify that text > 30K chars is truncated before calling generate_text."""
        long_text = "X" * 40_000
        mock_response = MagicMock()
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100,
            candidates_token_count=50,
        )

        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            return_value=(json.dumps(_VALID_JSON), mock_response),
        ) as mock_gen, patch(
            "core.ai_client.get_ai_model", return_value="gemini-2.5-pro"
        ), patch(
            "core.token_logger.log_token_usage"
        ):
            result = await extract_knowledge(long_text, title="Long Article")

            # Verify generate_text was called
            assert mock_gen.call_count == 1
            call_args = mock_gen.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][1]
            user_msg = messages[0]["content"]
            # The article portion should be truncated to _MAX_CONTENT_LENGTH
            assert len(user_msg) < 40_000
            assert result is not None

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_returns_result_on_valid_json(self):
        mock_response = MagicMock()
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100,
            candidates_token_count=50,
        )

        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            return_value=(json.dumps(_VALID_JSON), mock_response),
        ), patch(
            "core.ai_client.get_ai_model", return_value="gemini-2.5-pro"
        ), patch(
            "core.token_logger.log_token_usage"
        ):
            result = await extract_knowledge(_ARTICLE_TEXT, title="Test Article", url="http://example.com")

            assert result is not None
            assert isinstance(result, ExtractionResult)
            assert len(result.claims) == 2
            assert len(result.frameworks) == 1
            assert len(result.action_items) == 2
            assert len(result.key_concepts) == 3
            assert result.summary == "This article discusses effective habits for productivity."

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_returns_none_on_api_failure(self):
        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API not configured"),
        ):
            result = await extract_knowledge(_ARTICLE_TEXT, title="T")
            assert result is None

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_json(self):
        mock_response = MagicMock()
        mock_response.usage_metadata = None

        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            return_value=("not valid json {{{", mock_response),
        ), patch(
            "core.ai_client.get_ai_model", return_value="gemini-2.5-pro"
        ), patch(
            "core.token_logger.log_token_usage"
        ):
            result = await extract_knowledge(_ARTICLE_TEXT, title="T")
            assert result is None

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_returns_none_on_non_dict_json(self):
        mock_response = MagicMock()
        mock_response.usage_metadata = None

        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            return_value=('["not", "a", "dict"]', mock_response),
        ), patch(
            "core.ai_client.get_ai_model", return_value="gemini-2.5-pro"
        ), patch(
            "core.token_logger.log_token_usage"
        ):
            result = await extract_knowledge(_ARTICLE_TEXT, title="T")
            assert result is None

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_strips_code_fences(self):
        fenced_json = '```json\n' + json.dumps(_VALID_JSON) + '\n```'
        mock_response = MagicMock()
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100,
            candidates_token_count=50,
        )

        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            return_value=(fenced_json, mock_response),
        ), patch(
            "core.ai_client.get_ai_model", return_value="gemini-2.5-pro"
        ), patch(
            "core.token_logger.log_token_usage"
        ):
            result = await extract_knowledge(_ARTICLE_TEXT, title="T")
            assert result is not None
            assert len(result.claims) == 2

    @pytest.mark.skip(reason="generate_text not yet implemented in ai_client")
    @pytest.mark.asyncio
    async def test_logs_tokens(self):
        mock_response = MagicMock()
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=200,
            candidates_token_count=100,
        )

        with patch(
            "core.ai_client.generate_text",
            new_callable=AsyncMock,
            return_value=(json.dumps(_VALID_JSON), mock_response),
        ), patch(
            "core.ai_client.get_ai_model", return_value="gemini-2.5-pro"
        ), patch(
            "core.token_logger.log_token_usage"
        ) as mock_log:
            await extract_knowledge(_ARTICLE_TEXT, title="T")

            mock_log.assert_called_once_with(
                mock_response,
                caller="content_extractor",
                model="gemini-2.5-pro",
            )


# ---------------------------------------------------------------------------
# _ensure_concept_stubs
# ---------------------------------------------------------------------------


class TestEnsureConceptStubs:
    def test_creates_new_concepts(self, temp_vault):
        """Should create concept files for concepts that don't exist."""
        (temp_vault / "Concepts").mkdir(exist_ok=True)

        with patch("config.VAULT_PATH", temp_vault), \
             patch("core.vault_ops._on_vault_write"):
            created = _ensure_concept_stubs(
                key_concepts=["New Concept", "Another Concept"],
                source_url="http://example.com",
                source_title="Test Article",
                icor_elements=["Mind & Growth"],
            )

            assert len(created) == 2
            # Check files exist
            assert (temp_vault / "Concepts" / "New-Concept.md").exists()
            assert (temp_vault / "Concepts" / "Another-Concept.md").exists()

            # Check content
            content = (temp_vault / "Concepts" / "New-Concept.md").read_text()
            assert "seedling" in content
            assert "Extracted from [Test Article](http://example.com)" in content
            assert "Mind & Growth" in content

    def test_skips_existing_concepts(self, temp_vault):
        """Should not overwrite existing concept files."""
        (temp_vault / "Concepts").mkdir(exist_ok=True)
        existing_path = temp_vault / "Concepts" / "Existing-Concept.md"
        existing_path.write_text("# Existing\n\nOriginal content.\n")

        with patch("config.VAULT_PATH", temp_vault), \
             patch("core.vault_ops._on_vault_write"):
            created = _ensure_concept_stubs(
                key_concepts=["Existing Concept"],
                source_url="http://example.com",
                source_title="Test",
            )

            assert len(created) == 0
            # Original content preserved
            assert "Original content." in existing_path.read_text()


# ---------------------------------------------------------------------------
# create_knowledge_note (tests via vault_ops)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="create_knowledge_note not yet implemented in vault_ops")
class TestCreateKnowledgeNote:
    def _make_extraction(self):
        """Build a sample ExtractionResult."""
        return ExtractionResult(
            claims=[
                ExtractedClaim(
                    text="Morning routines improve focus.",
                    confidence="high",
                    source_context="Studies show that...",
                ),
                ExtractedClaim(
                    text="Cold showers boost energy.",
                    confidence="medium",
                    source_context="Anecdotal evidence.",
                ),
            ],
            frameworks=[
                ExtractedFramework(name="GTD", description="Getting Things Done."),
            ],
            action_items=[
                ExtractedActionItem(
                    description="Create a morning routine checklist.",
                    context="From the habits section.",
                ),
            ],
            key_concepts=["Morning Routine", "Productivity"],
            summary="Article about productive habits and morning routines.",
            raw_json=_VALID_JSON,
        )

    def test_correct_frontmatter(self, temp_vault):
        """Knowledge note should have correct type and extraction stats in frontmatter."""
        (temp_vault / "Resources").mkdir(exist_ok=True)

        with patch("config.VAULT_PATH", temp_vault), \
             patch("core.vault_ops._on_vault_write"):
            from core.vault_ops import create_knowledge_note

            extraction = self._make_extraction()
            path = create_knowledge_note(
                url="http://example.com/article",
                title="Test Article",
                extraction=extraction,
                icor_elements=["Mind & Growth"],
            )

            assert path.exists()
            content = path.read_text()

            # Check frontmatter fields
            assert "type: knowledge_note" in content
            assert 'url: "http://example.com/article"' in content
            assert 'title: "Test Article"' in content
            assert "icor_elements: [Mind & Growth]" in content
            assert "claims: 2" in content
            assert "frameworks: 1" in content
            assert "actions: 1" in content

    def test_has_all_sections(self, temp_vault):
        """Knowledge note should contain Summary, Key Claims, Frameworks, Action Items, Key Concepts."""
        (temp_vault / "Resources").mkdir(exist_ok=True)

        with patch("config.VAULT_PATH", temp_vault), \
             patch("core.vault_ops._on_vault_write"):
            from core.vault_ops import create_knowledge_note

            extraction = self._make_extraction()
            path = create_knowledge_note(
                url="http://example.com/article",
                title="Test Article",
                extraction=extraction,
            )

            content = path.read_text()

            assert "## Summary" in content
            assert "Article about productive habits" in content
            assert "## Key Claims" in content
            assert "[high]" in content
            assert "[medium]" in content
            assert "Morning routines improve focus." in content
            assert "> Studies show that..." in content
            assert "## Frameworks" in content
            assert "### GTD" in content
            assert "Getting Things Done." in content
            assert "## Action Items" in content
            assert "- [ ] Create a morning routine checklist." in content
            assert "## Key Concepts" in content

    def test_wikilinks_concepts(self, temp_vault):
        """Key concepts section should contain [[wikilinks]]."""
        (temp_vault / "Resources").mkdir(exist_ok=True)

        with patch("config.VAULT_PATH", temp_vault), \
             patch("core.vault_ops._on_vault_write"):
            from core.vault_ops import create_knowledge_note

            extraction = self._make_extraction()
            path = create_knowledge_note(
                url="http://example.com",
                title="Test",
                extraction=extraction,
            )

            content = path.read_text()

            assert "[[Morning Routine]]" in content
            assert "[[Productivity]]" in content

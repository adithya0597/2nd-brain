"""Tests for handlers/capture.py — capture handler functions."""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    "Systems & Environment": "brain-systems",
}
cfg.DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness"],
    "Systems & Environment": ["system", "automate"],
}
cfg.PROJECT_KEYWORDS = ["project", "milestone"]
cfg.RESOURCE_KEYWORDS = ["article", "book"]
cfg.OWNER_TELEGRAM_ID = 12345
cfg.GROUP_CHAT_ID = -100123
cfg.TOPICS = {"brain-inbox": 1}
cfg.CONFIDENCE_THRESHOLD = 0.60

from handlers.capture import (
    get_classifier,
    _detect_project_mention,
    _detect_resource_mention,
    _cb,
    _log_classification,
    _INTENT_CONFIRM_LABELS,
    _pending_extractions,
    handle_capture,
    handle_extraction_confirm,
    handle_extraction_skip,
    _ingest_article,
    register,
)
from core.classifier import ClassificationResult, DimensionScore, MessageClassifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_detect_project_mention_true(self):
        assert _detect_project_mention("project milestone reached") is True

    def test_detect_project_mention_false(self):
        assert _detect_project_mention("just a thought") is False

    def test_detect_resource_mention_true(self):
        assert _detect_resource_mention("read this great article and book") is True

    def test_detect_resource_mention_false(self):
        assert _detect_resource_mention("hello world") is False

    def test_cb(self):
        result = _cb({"a": "test", "id": 1})
        parsed = json.loads(result)
        assert parsed["a"] == "test"

    def test_get_classifier(self):
        cls = get_classifier()
        assert cls is not None


# ---------------------------------------------------------------------------
# _log_classification
# ---------------------------------------------------------------------------

class TestLogClassification:
    @pytest.mark.asyncio
    async def test_log_with_matches(self):
        result = ClassificationResult()
        result.matches = [DimensionScore(dimension="Health", confidence=0.8, method="keyword")]

        with patch("handlers.capture.execute", new_callable=AsyncMock) as mock_exec:
            await _log_classification("gym workout", 123, result)
        mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_empty_matches(self):
        result = ClassificationResult()
        result.matches = []

        with patch("handlers.capture.execute", new_callable=AsyncMock) as mock_exec:
            await _log_classification("random text", 456, result)
        mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_error_handled(self):
        result = ClassificationResult()
        result.matches = []

        with patch("handlers.capture.execute", new_callable=AsyncMock, side_effect=Exception("db")):
            await _log_classification("text", 789, result)


# ---------------------------------------------------------------------------
# handle_capture
# ---------------------------------------------------------------------------

class TestHandleCapture:
    @pytest.fixture
    def mock_update(self):
        update = MagicMock()
        update.message.text = "Went for a run today"
        update.message.message_id = 100
        update.message.message_thread_id = 1  # inbox topic
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 12345
        update.effective_chat.id = -100123
        return update

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=200))
        ctx.application.create_task = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_no_message(self, mock_context):
        update = MagicMock()
        update.message = None
        await handle_capture(update, mock_context)

    @pytest.mark.asyncio
    async def test_non_owner_blocked(self, mock_update, mock_context):
        mock_update.effective_user.id = 99999
        with patch("handlers.capture.OWNER_TELEGRAM_ID", 12345):
            await handle_capture(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_topic_skipped(self, mock_update, mock_context):
        mock_update.message.message_thread_id = 999  # wrong topic
        with patch("handlers.capture.TOPICS", {"brain-inbox": 1}):
            await handle_capture(mock_update, mock_context)
        mock_update.message.reply_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noise_filtered(self, mock_update, mock_context):
        noise_result = ClassificationResult()
        noise_result.is_noise = True

        with (
            patch("handlers.capture.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.capture.TOPICS", {"brain-inbox": 1}),
            patch("handlers.capture.run_in_executor", new_callable=AsyncMock, return_value=noise_result),
        ):
            await handle_capture(mock_update, mock_context)

        mock_update.message.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_high_confidence_capture(self, mock_update, mock_context):
        result = ClassificationResult()
        result.is_noise = False
        result.is_actionable = False
        result.matches = [DimensionScore(dimension="Health & Vitality", confidence=0.9, method="keyword")]
        result.execution_time_ms = 10.0

        with (
            patch("handlers.capture.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.capture.TOPICS", {"brain-inbox": 1}),
            patch("handlers.capture.run_in_executor", new_callable=AsyncMock, side_effect=[result, None, None]),
            patch("handlers.capture._log_classification", new_callable=AsyncMock),
            patch("handlers.capture.execute", new_callable=AsyncMock),
            patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", None)),
        ):
            await handle_capture(mock_update, mock_context)


# ---------------------------------------------------------------------------
# _ingest_article
# ---------------------------------------------------------------------------

class TestIngestArticle:
    @pytest.mark.asyncio
    async def test_ingest_success(self):
        mock_article = MagicMock()
        mock_article.title = "Test Article"
        mock_article.content = "Some content about health and fitness."

        bot = MagicMock()
        bot.send_message = AsyncMock()

        with (
            patch("core.article_fetcher.fetch_article", return_value=mock_article),
            patch("core.vault_ops.create_web_clip"),
            patch("handlers.capture.run_in_executor", new_callable=AsyncMock, side_effect=[mock_article, None]),
        ):
            await _ingest_article(bot, -100, 1, "https://example.com", ["Health"])

    @pytest.mark.asyncio
    async def test_ingest_no_article(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()

        with patch("handlers.capture.run_in_executor", new_callable=AsyncMock, return_value=None):
            await _ingest_article(bot, -100, 1, "https://example.com", [])

    @pytest.mark.asyncio
    async def test_ingest_error(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()

        with patch("handlers.capture.run_in_executor", new_callable=AsyncMock, side_effect=Exception("fail")):
            await _ingest_article(bot, -100, 1, "https://example.com", [])


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_registers_handler(self):
        app = MagicMock()
        with patch("handlers.capture.ensure_dimension_pages"):
            register(app)
        # Message handler + 3 extraction callback handlers (ok, edit, skip)
        assert app.add_handler.call_count == 4


# ---------------------------------------------------------------------------
# Extraction gate + intent-aware UI tests
# ---------------------------------------------------------------------------


class TestExtractionGate:
    """Tests for the separated extraction gate and intent-aware buttons."""

    @pytest.fixture
    def mock_update(self):
        update = MagicMock()
        update.message.text = "remind me to call Sarah by Friday"
        update.message.message_id = 500
        update.message.message_thread_id = 1
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 12345
        update.effective_chat.id = -100123
        return update

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=200))
        ctx.application.create_task = MagicMock()
        return ctx

    def _make_extraction(self, intent="task", confidence=0.8, title="Call Sarah"):
        ext = MagicMock()
        ext.intent = intent
        ext.confidence = confidence
        ext.title = title
        ext.project = None
        ext.people = ["Sarah"]
        ext.due_date = "2026-04-04"
        ext.priority = None
        ext.raw_response = "{}"
        return ext

    @pytest.mark.asyncio
    async def test_extraction_ui_task_intent(self, mock_update, mock_context):
        """Task intent extraction shows 'Create Task' button via callback_data."""
        result = ClassificationResult()
        result.is_noise = False
        result.is_actionable = True
        result.matches = [DimensionScore(dimension="Relationships", confidence=0.9, method="keyword")]
        result.execution_time_ms = 10.0

        extraction = self._make_extraction(intent="task", confidence=0.8)

        with (
            patch("handlers.capture.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.capture.TOPICS", {"brain-inbox": 1}),
            patch("handlers.capture.run_in_executor", new_callable=AsyncMock, side_effect=[result, None, None]),
            patch("handlers.capture._log_classification", new_callable=AsyncMock),
            patch("handlers.capture.execute", new_callable=AsyncMock),
            patch("handlers.capture._classifier") as mock_cls,
            patch("core.intent_extractor.extract_intent", new_callable=AsyncMock, return_value=extraction),
            patch("core.intent_extractor._load_registry", return_value={}),
            patch("core.formatter.format_extraction_confirmation", return_value="<b>Task</b>"),
            patch("handlers.capture.InlineKeyboardButton") as mock_btn,
        ):
            mock_cls.check_should_extract.return_value = True
            await handle_capture(mock_update, mock_context)

        # Verify reply was sent and InlineKeyboardButton was called with "Create Task"
        mock_update.message.reply_text.assert_awaited()
        btn_labels = [call.args[0] for call in mock_btn.call_args_list if call.args]
        assert any("Create Task" in label for label in btn_labels)

    @pytest.mark.asyncio
    async def test_extraction_ui_idea_intent(self, mock_update, mock_context):
        """Idea intent extraction shows 'Save Idea' button."""
        mock_update.message.text = "idea about voice-controlled Obsidian"
        result = ClassificationResult()
        result.is_noise = False
        result.is_actionable = False
        result.matches = [DimensionScore(dimension="Systems & Environment", confidence=0.9, method="keyword")]
        result.execution_time_ms = 10.0

        extraction = self._make_extraction(intent="idea", confidence=0.7, title="Voice-controlled Obsidian")
        extraction.people = []
        extraction.due_date = None

        with (
            patch("handlers.capture.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.capture.TOPICS", {"brain-inbox": 1}),
            patch("handlers.capture.run_in_executor", new_callable=AsyncMock, side_effect=[result, None, None]),
            patch("handlers.capture._log_classification", new_callable=AsyncMock),
            patch("handlers.capture.execute", new_callable=AsyncMock),
            patch("handlers.capture._classifier") as mock_cls,
            patch("core.intent_extractor.extract_intent", new_callable=AsyncMock, return_value=extraction),
            patch("core.intent_extractor._load_registry", return_value={}),
            patch("core.formatter.format_extraction_confirmation", return_value="<b>Idea</b>"),
            patch("handlers.capture.InlineKeyboardButton") as mock_btn,
        ):
            mock_cls.check_should_extract.return_value = True
            await handle_capture(mock_update, mock_context)

        mock_update.message.reply_text.assert_awaited()
        btn_labels = [call.args[0] for call in mock_btn.call_args_list if call.args]
        assert any("Save Idea" in label for label in btn_labels)

    @pytest.mark.asyncio
    async def test_extraction_failure_fallback(self, mock_update, mock_context):
        """When extraction raises, fall back to dimension confirm."""
        result = ClassificationResult()
        result.is_noise = False
        result.is_actionable = True
        result.matches = [DimensionScore(dimension="Health & Vitality", confidence=0.9, method="keyword")]
        result.execution_time_ms = 10.0

        with (
            patch("handlers.capture.OWNER_TELEGRAM_ID", 12345),
            patch("handlers.capture.TOPICS", {"brain-inbox": 1}),
            patch("handlers.capture.run_in_executor", new_callable=AsyncMock, side_effect=[result, None, None]),
            patch("handlers.capture._log_classification", new_callable=AsyncMock),
            patch("handlers.capture.execute", new_callable=AsyncMock),
            patch("handlers.capture._classifier") as mock_cls,
            patch("core.intent_extractor.extract_intent", new_callable=AsyncMock, side_effect=Exception("LLM down")),
            patch("core.intent_extractor._load_registry", return_value={}),
            patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", None)),
        ):
            mock_cls.check_should_extract.return_value = True
            await handle_capture(mock_update, mock_context)

        # Should still get a reply (dimension confirm fallback)
        mock_update.message.reply_text.assert_awaited()

    def test_temporal_pattern_triggers_extraction(self):
        """'dentist Thursday' triggers should_extract but not is_actionable."""
        cls = MessageClassifier(keywords={"Health & Vitality": ["dentist"]})
        text = "dentist Thursday"
        assert cls._check_actionable(text) is False
        assert cls.check_should_extract(text) is True


class TestExtractionConfirmHandler:
    """Tests for intent-aware confirm handler."""

    @pytest.fixture
    def mock_query(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        return query

    def _make_extraction(self, intent="task", title="Call Sarah"):
        ext = MagicMock()
        ext.intent = intent
        ext.title = title
        ext.project = "Pitch Deck"
        ext.people = ["Sarah"]
        ext.due_date = "2026-04-04"
        ext.priority = None
        return ext

    @pytest.mark.asyncio
    async def test_task_confirm_creates_action_item(self, mock_query):
        """Task confirm calls insert_action_item + Notion push."""
        extraction = self._make_extraction(intent="task")
        _pending_extractions["600"] = (extraction, 9999999999.0)

        update = MagicMock()
        update.callback_query = mock_query
        mock_query.data = json.dumps({"a": "ext_ok", "e": "600"})

        ctx = MagicMock()
        ctx.job_queue = MagicMock()

        with (
            patch("handlers.capture.insert_action_item", new_callable=AsyncMock, return_value=1) as mock_insert,
            patch("handlers.capture._create_notion_task_immediate", new_callable=AsyncMock),
            patch("handlers.capture.execute", new_callable=AsyncMock),
            patch("core.formatter._esc", side_effect=lambda x: x),
        ):
            await handle_extraction_confirm(update, ctx)

        mock_insert.assert_awaited_once()
        mock_query.edit_message_text.assert_awaited_once()
        text = mock_query.edit_message_text.call_args[0][0]
        assert "Task created" in text

    @pytest.mark.asyncio
    async def test_nontask_confirm_skips_action_item(self, mock_query):
        """Non-task confirm does NOT call insert_action_item."""
        extraction = self._make_extraction(intent="idea", title="Voice Obsidian")
        _pending_extractions["601"] = (extraction, 9999999999.0)

        update = MagicMock()
        update.callback_query = mock_query
        mock_query.data = json.dumps({"a": "ext_ok", "e": "601"})

        ctx = MagicMock()

        with (
            patch("handlers.capture.insert_action_item", new_callable=AsyncMock) as mock_insert,
            patch("handlers.capture.execute", new_callable=AsyncMock) as mock_exec,
            patch("core.formatter._esc", side_effect=lambda x: x),
        ):
            await handle_extraction_confirm(update, ctx)

        mock_insert.assert_not_awaited()
        # Should log extraction_feedback
        mock_exec.assert_awaited()
        mock_query.edit_message_text.assert_awaited_once()
        text = mock_query.edit_message_text.call_args[0][0]
        assert "Idea noted" in text

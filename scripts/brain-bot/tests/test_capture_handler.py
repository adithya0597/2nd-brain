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
    handle_capture,
    _ingest_article,
    register,
)
from core.classifier import ClassificationResult, DimensionScore


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
        app.add_handler.assert_called_once()

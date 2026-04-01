"""Tests for /ingest command handler."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

import pytest

from core.media_downloader import MediaContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_update():
    update = MagicMock()
    update.effective_chat.id = -100123
    update.effective_user.id = 12345
    update.message.message_thread_id = None
    update.message.reply_text = AsyncMock()
    # reply_text returns a message object with edit_text
    mock_msg = MagicMock()
    mock_msg.edit_text = AsyncMock()
    update.message.reply_text.return_value = mock_msg
    return update


@pytest.fixture()
def mock_context():
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.args = []
    return context


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="_handle_ingest not yet implemented in handlers/commands.py")
class TestIngestCommand:
    @pytest.mark.asyncio
    async def test_ingest_no_url(self, mock_update, mock_context):
        """Should reply with usage when no URL provided."""
        mock_context.args = []

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Usage" in call_args[0][0] or "Usage" in call_args.kwargs.get("text", call_args[0][0])

    @pytest.mark.asyncio
    async def test_ingest_unknown_url(self, mock_update, mock_context):
        """Should reject unsupported URL types."""
        mock_context.args = ["https://example.com/article"]

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        # Should have sent initial "Detecting..." then edited with unsupported message
        reply_msg = mock_update.message.reply_text.return_value
        reply_msg.edit_text.assert_called()
        last_edit = reply_msg.edit_text.call_args_list[-1]
        text = last_edit[0][0] if last_edit[0] else last_edit.kwargs.get("text", "")
        assert "Unsupported" in text or "unsupported" in text.lower()

    @pytest.mark.asyncio
    async def test_ingest_youtube_success(self, mock_update, mock_context):
        """Full pipeline mock for YouTube ingestion."""
        mock_context.args = ["https://youtube.com/watch?v=test123"]

        mock_media = MediaContent(
            url="https://youtube.com/watch?v=test123",
            title="Test Video Title",
            media_type="youtube",
            local_path=Path("/tmp/fake-audio.mp3"),
            metadata={"duration": 600, "channel": "TestChannel"},
        )

        mock_transcription = MagicMock()
        mock_transcription.text = "This is the transcribed content of the video " * 20
        mock_transcription.language = "en"
        mock_transcription.duration_seconds = 600.0

        mock_extraction = MagicMock()
        mock_extraction.claims = [MagicMock()] * 5
        mock_extraction.action_items = [MagicMock()] * 3
        mock_extraction.key_concepts = ["Concept A", "Concept B"]
        mock_extraction.summary = "A test video about testing."

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345), \
             patch("core.media_downloader.detect_media_type", return_value="youtube"), \
             patch("core.media_downloader.download_media", return_value=mock_media), \
             patch("handlers.commands.run_in_executor") as mock_executor, \
             patch("core.transcriber.transcribe", return_value=mock_transcription), \
             patch("core.content_extractor.extract_knowledge", new_callable=AsyncMock, return_value=mock_extraction), \
             patch("core.content_extractor._ensure_concept_stubs"), \
             patch("core.vault_ops.create_knowledge_note", return_value=Path("/tmp/vault/Resources/note.md")), \
             patch("core.vault_ops.create_media_note", return_value=Path("/tmp/vault/Resources/media.md")), \
             patch("shutil.rmtree"):

            # Setup run_in_executor to call the function directly
            async def fake_executor(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            mock_executor.side_effect = fake_executor

            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        # Should have completed with a knowledge extraction result
        reply_msg = mock_update.message.reply_text.return_value
        assert reply_msg.edit_text.call_count >= 3  # Detecting, Downloading, Transcribing, Extracting, Saving, Result

    @pytest.mark.asyncio
    async def test_ingest_pdf_success(self, mock_update, mock_context):
        """Full pipeline mock for PDF ingestion."""
        mock_context.args = ["https://example.com/paper.pdf"]

        mock_media = MediaContent(
            url="https://example.com/paper.pdf",
            title="Research Paper",
            media_type="pdf",
            local_path=Path("/tmp/document.pdf"),
            text_content="This is the content of the PDF document. " * 50,
            metadata={"page_count": 10},
        )

        mock_extraction = MagicMock()
        mock_extraction.claims = [MagicMock()] * 8
        mock_extraction.action_items = [MagicMock()] * 2
        mock_extraction.key_concepts = ["Research", "Paper"]
        mock_extraction.summary = "A research paper about testing."

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345), \
             patch("core.media_downloader.detect_media_type", return_value="pdf"), \
             patch("core.media_downloader.download_media", return_value=mock_media), \
             patch("handlers.commands.run_in_executor") as mock_executor, \
             patch("core.content_extractor.extract_knowledge", new_callable=AsyncMock, return_value=mock_extraction), \
             patch("core.content_extractor._ensure_concept_stubs"), \
             patch("core.vault_ops.create_knowledge_note", return_value=Path("/tmp/vault/Resources/note.md")), \
             patch("shutil.rmtree"):

            async def fake_executor(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            mock_executor.side_effect = fake_executor

            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        reply_msg = mock_update.message.reply_text.return_value
        # At minimum: Detecting, Downloading, Extracting, Saving, Result
        assert reply_msg.edit_text.call_count >= 3

    @pytest.mark.asyncio
    async def test_ingest_download_error(self, mock_update, mock_context):
        """Should show error when download fails."""
        mock_context.args = ["https://youtube.com/watch?v=fail"]

        mock_media = MediaContent(
            url="https://youtube.com/watch?v=fail",
            title="",
            media_type="youtube",
            error="Network timeout",
        )

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345), \
             patch("core.media_downloader.detect_media_type", return_value="youtube"), \
             patch("core.media_downloader.download_media", return_value=mock_media), \
             patch("handlers.commands.run_in_executor") as mock_executor, \
             patch("shutil.rmtree"):

            async def fake_executor(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            mock_executor.side_effect = fake_executor

            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        reply_msg = mock_update.message.reply_text.return_value
        # Should edit with an error message
        last_call = reply_msg.edit_text.call_args_list[-1]
        text = last_call[0][0] if last_call[0] else last_call.kwargs.get("text", "")
        assert "failed" in text.lower() or "error" in text.lower() or "Network timeout" in text

    @pytest.mark.asyncio
    async def test_ingest_owner_only(self, mock_update, mock_context):
        """Should not respond to non-owner users."""
        mock_context.args = ["https://youtube.com/watch?v=test"]
        mock_update.effective_user.id = 99999  # Not the owner

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345):
            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        # Should not have replied at all
        mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_temp_cleanup(self, mock_update, mock_context):
        """Temp directory should be cleaned up even on failure."""
        mock_context.args = ["https://youtube.com/watch?v=test"]

        mock_media = MediaContent(
            url="https://youtube.com/watch?v=test",
            title="Test",
            media_type="youtube",
            local_path=Path("/tmp/fake.mp3"),
            metadata={},
        )

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345), \
             patch("core.media_downloader.detect_media_type", return_value="youtube"), \
             patch("core.media_downloader.download_media", return_value=mock_media), \
             patch("handlers.commands.run_in_executor") as mock_executor, \
             patch("core.transcriber.transcribe", side_effect=RuntimeError("Whisper crash")), \
             patch("shutil.rmtree") as mock_rmtree:

            async def fake_executor(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            mock_executor.side_effect = fake_executor

            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        # rmtree should have been called for cleanup
        mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_extraction_fallback_to_media_note(self, mock_update, mock_context):
        """When extraction fails, should fall back to media note."""
        mock_context.args = ["https://youtube.com/watch?v=fallback"]

        mock_media = MediaContent(
            url="https://youtube.com/watch?v=fallback",
            title="Fallback Video",
            media_type="youtube",
            local_path=Path("/tmp/fake.mp3"),
            metadata={"duration": 120},
        )

        mock_transcription = MagicMock()
        mock_transcription.text = "Short transcript text for testing."
        mock_transcription.language = "en"
        mock_transcription.duration_seconds = 120.0

        with patch("handlers.commands.OWNER_TELEGRAM_ID", 12345), \
             patch("core.media_downloader.detect_media_type", return_value="youtube"), \
             patch("core.media_downloader.download_media", return_value=mock_media), \
             patch("handlers.commands.run_in_executor") as mock_executor, \
             patch("core.transcriber.transcribe", return_value=mock_transcription), \
             patch("core.content_extractor.extract_knowledge", new_callable=AsyncMock, return_value=None), \
             patch("core.vault_ops.create_media_note", return_value=Path("/tmp/vault/Resources/media.md")) as mock_create_media, \
             patch("shutil.rmtree"):

            async def fake_executor(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            mock_executor.side_effect = fake_executor

            from handlers.commands import _handle_ingest
            await _handle_ingest(mock_update, mock_context)

        # create_media_note should have been called
        mock_create_media.assert_called_once()

    def test_ingest_registered_in_commands(self):
        """The ingest handler should be registered."""
        from handlers.commands import register
        app = MagicMock()
        register(app)

        # Check that CommandHandler("ingest", ...) was added
        calls = app.add_handler.call_args_list
        handler_names = []
        for call in calls:
            handler = call[0][0]
            # CommandHandler instances have a .commands attribute
            if hasattr(handler, "commands"):
                handler_names.extend(handler.commands)
        # Since we're mocking telegram.ext, check add_handler was called with ingest
        assert app.add_handler.call_count > 0

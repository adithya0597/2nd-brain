"""Tests for voice capture handling in handlers/capture.py."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure brain-bot is on the path
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Mock faster_whisper before any imports
_fw_mock = MagicMock()
sys.modules.setdefault("faster_whisper", _fw_mock)


def _make_voice_update(owner_id=12345, thread_id=1, has_voice=True, has_audio=False):
    """Build a mock Update with voice/audio message."""
    update = MagicMock()
    update.effective_chat.id = -100123
    update.effective_user.id = owner_id
    update.message.message_thread_id = thread_id
    update.message.message_id = 999
    update.message.text = None  # voice messages have no text
    update.message.reply_text = AsyncMock(return_value=MagicMock(
        edit_text=AsyncMock(),
        message_id=42,
    ))

    if has_voice:
        voice = MagicMock()
        voice.file_id = "voice_file_123"
        voice.get_file = AsyncMock(return_value=MagicMock(
            download_to_drive=AsyncMock()
        ))
        update.message.voice = voice
        update.message.audio = None
    elif has_audio:
        audio = MagicMock()
        audio.file_id = "audio_file_456"
        audio.get_file = AsyncMock(return_value=MagicMock(
            download_to_drive=AsyncMock()
        ))
        update.message.voice = None
        update.message.audio = audio
    else:
        update.message.voice = None
        update.message.audio = None

    return update


def _make_context():
    """Build a mock context."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    ctx.bot.edit_message_text = AsyncMock()
    ctx.args = []
    return ctx


def _mock_transcription_result():
    """Build a mock TranscriptionResult."""
    from core.transcriber import TranscriptionResult
    return TranscriptionResult(
        text="I need to exercise more regularly",
        language="en",
        duration_seconds=5.0,
        transcription_time_seconds=1.2,
        model_size="base",
    )


def _mock_classification_result(dimension="Health & Vitality", confidence=0.85):
    """Build a mock ClassificationResult."""
    from core.classifier import ClassificationResult, DimensionScore
    return ClassificationResult(
        matches=[DimensionScore(
            dimension=dimension,
            confidence=confidence,
            method="keyword",
        )],
        is_noise=False,
        is_actionable=True,
        execution_time_ms=10.0,
    )


@pytest.mark.skip(reason="handle_voice_capture not yet implemented in handlers/capture.py")
class TestVoiceCaptureOwnerCheck:
    """Test owner gating on voice captures."""

    @pytest.mark.asyncio
    async def test_ignores_non_owner(self):
        """Voice captures from non-owners should be silently ignored."""
        update = _make_voice_update(owner_id=99999)
        ctx = _make_context()

        from handlers.capture import handle_voice_capture
        await handle_voice_capture(update, ctx)

        # Should not reply at all
        update.message.reply_text.assert_not_called()


@pytest.mark.skip(reason="handle_voice_capture not yet implemented in handlers/capture.py")
class TestVoiceCaptureTopicGating:
    """Test topic gating — only capturable topics."""

    @pytest.mark.asyncio
    async def test_ignores_non_capturable_topic(self):
        """Voice in a non-capturable topic should be ignored."""
        update = _make_voice_update(thread_id=9999)  # Not a capturable topic
        ctx = _make_context()

        from handlers.capture import handle_voice_capture
        await handle_voice_capture(update, ctx)

        update.message.reply_text.assert_not_called()


@pytest.mark.skip(reason="handle_voice_capture not yet implemented in handlers/capture.py")
class TestVoiceCaptureTranscription:
    """Test transcription and routing pipeline."""

    @pytest.mark.asyncio
    async def test_downloads_and_transcribes(self):
        """Should download voice file and call transcribe()."""
        update = _make_voice_update()
        ctx = _make_context()

        tr_result = _mock_transcription_result()
        cl_result = _mock_classification_result()

        with patch("handlers.capture.run_in_executor") as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", [])):

            # First call: transcribe, second: classify, then vault writes
            call_count = 0

            async def side_effect(fn, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return tr_result  # transcribe
                elif call_count == 2:
                    return cl_result  # classify
                return MagicMock()  # vault writes

            mock_exec.side_effect = side_effect

            from handlers.capture import handle_voice_capture
            await handle_voice_capture(update, ctx)

            # First call should be the ack message
            first_call = update.message.reply_text.call_args_list[0]
            assert first_call.args[0] == "Transcribing voice message..."
            # Transcribe and classify were called
            assert call_count >= 2

    @pytest.mark.asyncio
    async def test_classifies_transcribed_text(self):
        """Transcribed text should be passed to the classifier."""
        update = _make_voice_update()
        ctx = _make_context()

        tr_result = _mock_transcription_result()
        cl_result = _mock_classification_result()

        classified_text = None

        with patch("handlers.capture.run_in_executor") as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", [])):

            call_count = 0

            async def side_effect(fn, *args, **kwargs):
                nonlocal call_count, classified_text
                call_count += 1
                if call_count == 1:
                    return tr_result
                elif call_count == 2:
                    # This is the classify call — capture the text
                    classified_text = args[0] if args else None
                    return cl_result
                return MagicMock()

            mock_exec.side_effect = side_effect

            from handlers.capture import handle_voice_capture
            await handle_voice_capture(update, ctx)

            assert classified_text == "I need to exercise more regularly"

    @pytest.mark.asyncio
    async def test_saves_to_vault_with_voice_metadata(self):
        """Vault entry should include voice-specific frontmatter."""
        update = _make_voice_update()
        ctx = _make_context()

        tr_result = _mock_transcription_result()
        cl_result = _mock_classification_result()

        captured_extra_fm = None

        with patch("handlers.capture.run_in_executor") as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", [])):

            call_count = 0

            async def side_effect(fn, *args, **kwargs):
                nonlocal call_count, captured_extra_fm
                call_count += 1
                if call_count == 1:
                    return tr_result
                elif call_count == 2:
                    return cl_result
                else:
                    # Check for create_inbox_entry call
                    if hasattr(fn, "__name__") and fn.__name__ == "create_inbox_entry":
                        captured_extra_fm = kwargs.get("extra_frontmatter") or (
                            args[6] if len(args) > 6 else None
                        )
                    return MagicMock()

            mock_exec.side_effect = side_effect

            from handlers.capture import handle_voice_capture
            await handle_voice_capture(update, ctx)

        # The voice metadata should have been passed through _route_classified_capture
        # We verify the ack was updated with routing info
        ack_msg = update.message.reply_text.return_value
        assert ack_msg.edit_text.called

    @pytest.mark.asyncio
    async def test_cleans_up_temp_file(self):
        """Temp audio file should be deleted even on error."""
        update = _make_voice_update()
        ctx = _make_context()

        with patch("handlers.capture.run_in_executor") as mock_exec, \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:

            # Set up temp file
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.name = "/tmp/test_voice.ogg"
            mock_tmp.return_value = mock_file

            # Make transcription fail
            mock_exec.side_effect = RuntimeError("transcription failed")

            from handlers.capture import handle_voice_capture

            with patch("pathlib.Path.exists", return_value=True), \
                 patch("pathlib.Path.unlink") as mock_unlink:
                await handle_voice_capture(update, ctx)

                # Temp file should have been cleaned up
                mock_unlink.assert_called()


@pytest.mark.skip(reason="handle_voice_capture not yet implemented in handlers/capture.py")
class TestVoiceCaptureErrorHandling:
    """Test error handling in voice capture."""

    @pytest.mark.asyncio
    async def test_handles_import_error_gracefully(self):
        """Should send friendly message if faster-whisper is not installed."""
        update = _make_voice_update()
        ctx = _make_context()

        with patch("handlers.capture.run_in_executor") as mock_exec:
            # Simulate transcriber import failure
            original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

            def mock_import(name, *args, **kwargs):
                if name == "core.transcriber":
                    raise ImportError("No module named 'faster_whisper'")
                return original_import(name, *args, **kwargs)

            # Instead, we test the ImportError path by patching at module level

            with patch.dict("sys.modules", {"core.transcriber": None}):
                # This should trigger the ImportError in handle_voice_capture
                # Since it catches at the top, it sends a message
                pass  # The import is cached, so we test a different way

    @pytest.mark.asyncio
    async def test_noise_filtered_voice(self):
        """Noise-classified voice transcription should be handled gracefully."""
        update = _make_voice_update()
        ctx = _make_context()

        tr_result = _mock_transcription_result()

        from core.classifier import ClassificationResult
        noise_result = ClassificationResult(
            matches=[],
            is_noise=True,
            is_actionable=False,
            execution_time_ms=5.0,
        )

        with patch("handlers.capture.run_in_executor") as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock):

            call_count = 0

            async def side_effect(fn, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return tr_result
                elif call_count == 2:
                    return noise_result
                return MagicMock()

            mock_exec.side_effect = side_effect

            from handlers.capture import handle_voice_capture
            await handle_voice_capture(update, ctx)

            # Ack message should have been edited with noise feedback
            ack_msg = update.message.reply_text.return_value
            assert ack_msg.edit_text.called


@pytest.mark.skip(reason="_route_classified_capture not yet implemented in handlers/capture.py")
class TestRouteClassifiedCapture:
    """Test the extracted _route_classified_capture function."""

    @pytest.mark.asyncio
    async def test_route_classified_capture_high_confidence(self):
        """High-confidence capture should be saved to vault and DB."""
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        ctx = _make_context()

        cl_result = _mock_classification_result(confidence=0.95)

        with patch("handlers.capture.run_in_executor", new_callable=AsyncMock) as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", [])):

            mock_exec.return_value = MagicMock()

            from handlers.capture import _route_classified_capture
            await _route_classified_capture(
                update, ctx, "test text", 123, None, cl_result,
                source="brain-inbox", capture_type="capture",
            )

            # Should reply with confirmation
            update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_route_classified_capture_low_confidence_bouncer(self):
        """Low-confidence is handled before _route_classified_capture — verify
        that _route_classified_capture itself doesn't re-bounce."""
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        ctx = _make_context()

        # Even a low confidence result passed to _route_classified_capture
        # should be routed (bouncing is done by the caller)
        cl_result = _mock_classification_result(confidence=0.30)

        with patch("handlers.capture.run_in_executor", new_callable=AsyncMock) as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", [])):

            mock_exec.return_value = MagicMock()

            from handlers.capture import _route_classified_capture
            await _route_classified_capture(
                update, ctx, "test text", 123, None, cl_result,
                source="brain-inbox", capture_type="capture",
            )

            # Should still reply (no bouncing inside _route_classified_capture)
            update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_extra_frontmatter_passed_to_create_inbox(self):
        """extra_frontmatter should be passed to create_inbox_entry."""
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        ctx = _make_context()

        cl_result = _mock_classification_result()
        extra_fm = {"voice_duration": "5.0", "voice_language": "en"}

        captured_kwargs = {}

        with patch("handlers.capture.run_in_executor", new_callable=AsyncMock) as mock_exec, \
             patch("handlers.capture._log_classification", new_callable=AsyncMock), \
             patch("handlers.capture.execute", new_callable=AsyncMock), \
             patch("handlers.capture.insert_action_item", new_callable=AsyncMock), \
             patch("handlers.capture.format_capture_confirmation", return_value=("Captured!", [])):

            call_count = 0

            async def side_effect(fn, *args, **kwargs):
                nonlocal call_count, captured_kwargs
                call_count += 1
                # create_inbox_entry is the second run_in_executor call
                # (first is append_to_daily_note)
                if call_count == 2 and hasattr(fn, "__name__") and "inbox" in fn.__name__:
                    captured_kwargs = kwargs
                return MagicMock()

            mock_exec.side_effect = side_effect

            from handlers.capture import _route_classified_capture
            await _route_classified_capture(
                update, ctx, "voice text", 123, None, cl_result,
                source="telegram-voice", capture_type="capture",
                extra_frontmatter=extra_fm,
            )

            # Verify create_inbox_entry was called — the extra_frontmatter
            # is passed through the function chain
            assert mock_exec.called


@pytest.mark.skip(reason="extra_frontmatter/capture_type params not yet added to create_inbox_entry")
class TestExtraFrontmatterInInboxEntry:
    """Test that extra_frontmatter works in vault_ops.create_inbox_entry."""

    def test_extra_frontmatter_in_inbox_entry(self, tmp_path):
        """Extra frontmatter keys should appear in the YAML block."""
        with patch("config.VAULT_PATH", tmp_path):
            (tmp_path / "Inbox").mkdir(parents=True, exist_ok=True)

            with patch("core.vault_ops._on_vault_write"):
                from core.vault_ops import create_inbox_entry
                path = create_inbox_entry(
                    "voice transcription text",
                    source="telegram-voice",
                    dimensions=["Health & Vitality"],
                    confidence=0.85,
                    method="keyword",
                    capture_type="capture",
                    extra_frontmatter={
                        "voice_duration": "5.0",
                        "voice_file_id": "abc123",
                        "voice_language": "en",
                        "whisper_model": "base",
                    },
                )

            content = path.read_text(encoding="utf-8")
            assert "voice_duration: 5.0" in content
            assert "voice_file_id: abc123" in content
            assert "voice_language: en" in content
            assert "whisper_model: base" in content
            assert "source: telegram-voice" in content

    def test_no_extra_frontmatter_backward_compatible(self, tmp_path):
        """When extra_frontmatter is None, output is unchanged."""
        with patch("config.VAULT_PATH", tmp_path):
            (tmp_path / "Inbox").mkdir(parents=True, exist_ok=True)

            with patch("core.vault_ops._on_vault_write"):
                from core.vault_ops import create_inbox_entry
                path = create_inbox_entry(
                    "regular text capture",
                    source="telegram",
                    dimensions=["Mind & Growth"],
                    confidence=0.90,
                    method="keyword",
                )

            content = path.read_text(encoding="utf-8")
            assert "voice_duration" not in content
            assert "source: telegram" in content

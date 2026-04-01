"""Tests for core.transcriber — voice transcription via faster-whisper."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure brain-bot is on the path
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Mock faster_whisper before importing transcriber
_fw_mock = MagicMock()
sys.modules.setdefault("faster_whisper", _fw_mock)


class TestTranscriberSingleton:
    """Tests for lazy model loading and singleton pattern."""

    def setup_method(self):
        # Reset the singleton before each test
        from core import transcriber
        transcriber.reset_model()

    def test_lazy_load_creates_model(self):
        """_get_model() should lazy-load WhisperModel on first call."""
        from core import transcriber

        mock_model = MagicMock()
        _fw_mock.WhisperModel.return_value = mock_model

        transcriber.reset_model()
        result = transcriber._get_model()

        assert result is mock_model
        _fw_mock.WhisperModel.assert_called_once()

    def test_singleton_returns_same_model(self):
        """Subsequent _get_model() calls return the same instance."""
        from core import transcriber

        mock_model = MagicMock()
        _fw_mock.WhisperModel.reset_mock()
        _fw_mock.WhisperModel.return_value = mock_model

        transcriber.reset_model()
        first = transcriber._get_model()
        second = transcriber._get_model()

        assert first is second
        # WhisperModel should only be instantiated once
        assert _fw_mock.WhisperModel.call_count == 1

    def test_reset_model_clears_singleton(self):
        """reset_model() should clear the cached model."""
        from core import transcriber

        mock_model = MagicMock()
        _fw_mock.WhisperModel.return_value = mock_model

        transcriber.reset_model()
        transcriber._get_model()
        transcriber.reset_model()

        # After reset, _whisper_model should be None
        assert transcriber._whisper_model is None


class TestTranscribe:
    """Tests for the transcribe() function."""

    def setup_method(self):
        from core import transcriber
        transcriber.reset_model()

    def test_returns_transcription_result(self, tmp_path):
        """transcribe() should return a TranscriptionResult dataclass."""
        from core.transcriber import transcribe, TranscriptionResult

        # Create a fake audio file
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")

        # Mock the model and its transcribe method
        mock_segment = MagicMock()
        mock_segment.text = "Hello world"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 5.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        _fw_mock.WhisperModel.return_value = mock_model

        result = transcribe(audio_file)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 5.0
        assert result.transcription_time_seconds >= 0
        assert result.model_size == "base"

    def test_raises_on_missing_file(self):
        """transcribe() should raise FileNotFoundError for missing audio."""
        from core.transcriber import transcribe

        with pytest.raises(FileNotFoundError):
            transcribe(Path("/nonexistent/audio.ogg"))

    def test_raises_on_empty_result(self, tmp_path):
        """transcribe() should raise RuntimeError if text is empty."""
        from core.transcriber import transcribe

        audio_file = tmp_path / "empty.ogg"
        audio_file.write_bytes(b"fake audio")

        mock_segment = MagicMock()
        mock_segment.text = "   "
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 1.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        _fw_mock.WhisperModel.return_value = mock_model

        with pytest.raises(RuntimeError, match="empty text"):
            transcribe(audio_file)

    def test_vad_filter_enabled(self, tmp_path):
        """transcribe() should call model.transcribe with vad_filter=True."""
        from core.transcriber import transcribe

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio")

        mock_segment = MagicMock()
        mock_segment.text = "Test speech"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 3.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        _fw_mock.WhisperModel.return_value = mock_model

        transcribe(audio_file)

        mock_model.transcribe.assert_called_once()
        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs[1].get("vad_filter") is True or call_kwargs.kwargs.get("vad_filter") is True

    def test_beam_size_5(self, tmp_path):
        """transcribe() should call model.transcribe with beam_size=5."""
        from core.transcriber import transcribe

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio")

        mock_segment = MagicMock()
        mock_segment.text = "Test speech"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 3.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        _fw_mock.WhisperModel.return_value = mock_model

        transcribe(audio_file)

        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs[1].get("beam_size") == 5 or call_kwargs.kwargs.get("beam_size") == 5

    def test_config_model_used(self, tmp_path):
        """transcribe() should use config.WHISPER_MODEL and config.WHISPER_DEVICE."""
        from core import transcriber

        transcriber.reset_model()

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio")

        mock_segment = MagicMock()
        mock_segment.text = "Hello"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 2.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        _fw_mock.WhisperModel.return_value = mock_model

        with patch.object(sys.modules["config"], "WHISPER_MODEL", "small", create=True), \
             patch.object(sys.modules["config"], "WHISPER_DEVICE", "cuda", create=True):
            transcriber.reset_model()
            transcriber.transcribe(audio_file)

        _fw_mock.WhisperModel.assert_called_with(
            "small", device="cuda", compute_type="int8"
        )

    def test_multiple_segments_joined(self, tmp_path):
        """transcribe() should join text from multiple segments."""
        from core.transcriber import transcribe

        audio_file = tmp_path / "multi.ogg"
        audio_file.write_bytes(b"fake audio")

        seg1 = MagicMock()
        seg1.text = "First part."
        seg2 = MagicMock()
        seg2.text = "Second part."
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 10.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg1, seg2], mock_info)
        _fw_mock.WhisperModel.return_value = mock_model

        from core import transcriber
        transcriber.reset_model()
        result = transcribe(audio_file)

        assert result.text == "First part. Second part."


class TestImportError:
    """Tests for graceful degradation when faster-whisper is missing."""

    def test_get_model_returns_none_on_import_error(self):
        """_get_model() should return None if faster-whisper import fails."""
        from core import transcriber
        transcriber.reset_model()

        # Temporarily make WhisperModel raise ImportError
        original = _fw_mock.WhisperModel
        _fw_mock.WhisperModel = MagicMock(side_effect=ImportError("no faster-whisper"))

        try:
            result = transcriber._get_model()
            assert result is None
        finally:
            _fw_mock.WhisperModel = original

    def test_transcribe_raises_import_error_when_unavailable(self, tmp_path):
        """transcribe() should raise ImportError if model can't load."""
        from core import transcriber
        transcriber.reset_model()

        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio")

        original = _fw_mock.WhisperModel
        _fw_mock.WhisperModel = MagicMock(side_effect=ImportError("no faster-whisper"))

        try:
            with pytest.raises(ImportError, match="faster-whisper"):
                transcriber.transcribe(audio_file)
        finally:
            _fw_mock.WhisperModel = original

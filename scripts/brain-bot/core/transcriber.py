"""Voice transcription via faster-whisper.

Provides a singleton WhisperModel and a transcribe() function that returns
structured results. Gracefully degrades if faster-whisper is not installed.
"""
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Thread-safe singleton for the Whisper model
_model_lock = threading.Lock()
_whisper_model = None


@dataclass
class TranscriptionResult:
    """Result of a voice transcription."""

    text: str
    language: str
    duration_seconds: float
    transcription_time_seconds: float
    model_size: str


def _get_model():
    """Thread-safe lazy singleton for the WhisperModel.

    Returns the WhisperModel instance or None if faster-whisper is not installed.
    Uses config.WHISPER_MODEL and config.WHISPER_DEVICE.
    """
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model if _whisper_model is not False else None

    with _model_lock:
        # Double-check after acquiring lock
        if _whisper_model is not None:
            return _whisper_model if _whisper_model is not False else None

        try:
            from faster_whisper import WhisperModel

            model_size = getattr(config, "WHISPER_MODEL", "base")
            device = getattr(config, "WHISPER_DEVICE", "cpu")
            logger.info("Loading Whisper model %s on %s...", model_size, device)
            _whisper_model = WhisperModel(
                model_size, device=device, compute_type="int8"
            )
            logger.info("Whisper model loaded: %s", model_size)
            return _whisper_model
        except ImportError:
            logger.warning("faster-whisper not installed — voice transcription disabled")
            _whisper_model = False
            return None
        except Exception:
            logger.exception("Failed to load Whisper model")
            _whisper_model = False
            return None


def reset_model():
    """Reset the singleton model (for tests)."""
    global _whisper_model
    with _model_lock:
        _whisper_model = None


def transcribe(audio_path: Path) -> TranscriptionResult:
    """Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file (ogg, mp3, wav, etc.).

    Returns:
        TranscriptionResult with the transcribed text and metadata.

    Raises:
        FileNotFoundError: If the audio file does not exist.
        ImportError: If faster-whisper is not installed.
        RuntimeError: If transcription produces empty text.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = _get_model()
    if model is None:
        raise ImportError(
            "faster-whisper is not installed. Install with: pip install faster-whisper>=1.0.0"
        )

    start = time.monotonic()
    segments, info = model.transcribe(
        str(audio_path), vad_filter=True, beam_size=5
    )
    text = " ".join(segment.text.strip() for segment in segments)
    elapsed = time.monotonic() - start

    if not text.strip():
        raise RuntimeError("Transcription produced empty text")

    model_size = getattr(config, "WHISPER_MODEL", "base")

    return TranscriptionResult(
        text=text.strip(),
        language=info.language,
        duration_seconds=info.duration,
        transcription_time_seconds=round(elapsed, 2),
        model_size=model_size,
    )

"""Media download and type detection for the ingestion pipeline.

Supports YouTube (via yt-dlp), podcasts (direct audio URLs), and PDFs
(via pdfplumber). All downloads are blocking I/O and should be called
from an executor.
"""
import logging
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Regex patterns for media type detection
_YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)[\w-]+",
    re.IGNORECASE,
)
_PDF_RE = re.compile(r"\.pdf(?:\?.*)?$", re.IGNORECASE)
_AUDIO_RE = re.compile(r"\.(mp3|m4a|ogg|wav|flac|aac)(?:\?.*)?$", re.IGNORECASE)

_USER_AGENT = "Mozilla/5.0 (compatible; SecondBrain/1.0)"
_SOCKET_TIMEOUT = 30


@dataclass
class MediaContent:
    """Result of a media download attempt."""

    url: str
    title: str
    media_type: str  # "youtube" | "podcast" | "pdf" | "unknown"
    local_path: Path | None = None  # temp file path (audio/pdf)
    text_content: str | None = None  # extracted text (PDF only)
    metadata: dict = field(default_factory=dict)  # duration, channel, page_count, etc.
    error: str | None = None  # error message if download failed


def detect_media_type(url: str) -> str:
    """Detect media type from a URL.

    Returns:
        One of "youtube", "pdf", "podcast", or "unknown".
    """
    if not url:
        return "unknown"

    if _YOUTUBE_RE.search(url):
        return "youtube"

    if _PDF_RE.search(url):
        return "pdf"

    if _AUDIO_RE.search(url):
        return "podcast"

    return "unknown"


def download_youtube(url: str, output_dir: Path) -> MediaContent:
    """Download audio from a YouTube video using yt-dlp.

    Args:
        url: YouTube video URL.
        output_dir: Directory to save the downloaded audio.

    Returns:
        MediaContent with local_path set to the downloaded audio file.
    """
    try:
        import yt_dlp
    except ImportError:
        return MediaContent(
            url=url,
            title="",
            media_type="youtube",
            error="yt-dlp is not installed. Install with: pip install yt-dlp",
        )

    output_template = str(output_dir / "%(title)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "socket_timeout": _SOCKET_TIMEOUT,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return MediaContent(
                    url=url, title="", media_type="youtube",
                    error="Failed to extract video info",
                )

            title = info.get("title", "Untitled")
            duration = info.get("duration", 0)
            channel = info.get("channel", info.get("uploader", ""))

            # Find the downloaded file (yt-dlp may change extension after postprocessing)
            downloaded_files = list(output_dir.glob("*"))
            if not downloaded_files:
                return MediaContent(
                    url=url, title=title, media_type="youtube",
                    error="Download completed but no file found",
                )

            local_path = downloaded_files[0]

            return MediaContent(
                url=url,
                title=title,
                media_type="youtube",
                local_path=local_path,
                metadata={
                    "duration": duration,
                    "channel": channel,
                    "video_id": info.get("id", ""),
                },
            )
    except Exception as e:
        logger.warning("YouTube download failed for %s: %s", url, e)
        return MediaContent(
            url=url, title="", media_type="youtube",
            error=f"Download failed: {e}",
        )


def download_pdf(url: str, output_dir: Path) -> MediaContent:
    """Download and extract text from a PDF.

    Args:
        url: URL to the PDF file.
        output_dir: Directory to save the downloaded PDF.

    Returns:
        MediaContent with text_content set to the extracted text.
    """
    try:
        import pdfplumber
    except ImportError:
        return MediaContent(
            url=url,
            title="",
            media_type="pdf",
            error="pdfplumber is not installed. Install with: pip install pdfplumber",
        )

    # Download the PDF
    local_path = output_dir / "document.pdf"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_SOCKET_TIMEOUT) as response:
            with open(local_path, "wb") as f:
                shutil.copyfileobj(response, f)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("PDF download failed for %s: %s", url, e)
        return MediaContent(
            url=url, title="", media_type="pdf",
            error=f"Download failed: {e}",
        )

    # Extract text
    try:
        text_parts = []
        page_count = 0
        with pdfplumber.open(local_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        text_content = "\n\n".join(text_parts)
        title = local_path.stem

        # Try to extract title from first line of text
        if text_content:
            first_line = text_content.strip().split("\n")[0].strip()
            if 5 < len(first_line) < 200:
                title = first_line

        return MediaContent(
            url=url,
            title=title,
            media_type="pdf",
            local_path=local_path,
            text_content=text_content,
            metadata={"page_count": page_count},
        )
    except Exception as e:
        logger.warning("PDF text extraction failed for %s: %s", url, e)
        return MediaContent(
            url=url, title="", media_type="pdf",
            local_path=local_path,
            error=f"Text extraction failed: {e}",
        )


def download_podcast(url: str, output_dir: Path) -> MediaContent:
    """Download an audio file from a direct URL.

    Args:
        url: Direct URL to an audio file (.mp3, .m4a, .ogg, etc.).
        output_dir: Directory to save the downloaded file.

    Returns:
        MediaContent with local_path set to the downloaded audio file.
    """
    # Determine extension from URL
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = ".mp3"  # default
    for audio_ext in (".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac"):
        if audio_ext in path:
            ext = audio_ext
            break

    local_path = output_dir / f"audio{ext}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_SOCKET_TIMEOUT) as response:
            with open(local_path, "wb") as f:
                shutil.copyfileobj(response, f)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("Podcast download failed for %s: %s", url, e)
        return MediaContent(
            url=url, title="", media_type="podcast",
            error=f"Download failed: {e}",
        )

    # Extract title from filename in URL
    filename = parsed.path.rsplit("/", 1)[-1] if "/" in parsed.path else "audio"
    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    title = urllib.request.url2pathname(title)  # decode %20 etc.

    return MediaContent(
        url=url,
        title=title or "Untitled Podcast",
        media_type="podcast",
        local_path=local_path,
        metadata={},
    )


def download_media(url: str, output_dir: Path | None = None) -> MediaContent:
    """Detect media type and download accordingly.

    Args:
        url: URL to download.
        output_dir: Directory for temp files. Creates a tempdir if None.

    Returns:
        MediaContent with download results.
    """
    media_type = detect_media_type(url)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="brain-media-"))

    output_dir.mkdir(parents=True, exist_ok=True)

    if media_type == "youtube":
        return download_youtube(url, output_dir)
    elif media_type == "pdf":
        return download_pdf(url, output_dir)
    elif media_type == "podcast":
        return download_podcast(url, output_dir)
    else:
        return MediaContent(
            url=url,
            title="",
            media_type="unknown",
            error="Unsupported media type. Provide a YouTube, podcast, or PDF URL.",
        )

"""Tests for core.media_downloader module."""
import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())


from core.media_downloader import (
    MediaContent,
    detect_media_type,
    download_media,
    download_pdf,
    download_podcast,
    download_youtube,
)


# ---------------------------------------------------------------------------
# detect_media_type
# ---------------------------------------------------------------------------

class TestDetectMediaType:
    def test_youtube_watch(self):
        assert detect_media_type("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube"

    def test_youtube_short(self):
        assert detect_media_type("https://youtube.com/shorts/abc123") == "youtube"

    def test_youtube_mobile(self):
        assert detect_media_type("https://youtu.be/dQw4w9WgXcQ") == "youtube"

    def test_youtube_embed(self):
        assert detect_media_type("https://www.youtube.com/embed/dQw4w9WgXcQ") == "youtube"

    def test_pdf(self):
        assert detect_media_type("https://example.com/paper.pdf") == "pdf"

    def test_pdf_with_query(self):
        assert detect_media_type("https://example.com/paper.pdf?dl=1") == "pdf"

    def test_mp3(self):
        assert detect_media_type("https://example.com/episode.mp3") == "podcast"

    def test_m4a(self):
        assert detect_media_type("https://example.com/podcast.m4a") == "podcast"

    def test_ogg(self):
        assert detect_media_type("https://example.com/voice.ogg") == "podcast"

    def test_wav(self):
        assert detect_media_type("https://example.com/sound.wav") == "podcast"

    def test_unknown_url(self):
        assert detect_media_type("https://example.com/article") == "unknown"

    def test_empty_string(self):
        assert detect_media_type("") == "unknown"

    def test_plain_text(self):
        assert detect_media_type("not a url") == "unknown"

    def test_html_page(self):
        assert detect_media_type("https://example.com/page.html") == "unknown"


# ---------------------------------------------------------------------------
# download_youtube
# ---------------------------------------------------------------------------

class TestDownloadYoutube:
    def test_success(self, tmp_path):
        """Mock yt-dlp to simulate a successful download."""
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.return_value = {
            "title": "Test Video",
            "duration": 300,
            "channel": "Test Channel",
            "id": "abc123",
        }
        mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
        mock_ydl_instance.__exit__ = MagicMock(return_value=False)

        # Create a fake downloaded file
        fake_audio = tmp_path / "Test Video.mp3"
        fake_audio.write_bytes(b"fake audio data")

        mock_yt_dlp = MagicMock()
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl_instance

        with patch.dict(sys.modules, {"yt_dlp": mock_yt_dlp}):
            result = download_youtube("https://youtube.com/watch?v=abc123", tmp_path)

        assert result.error is None
        assert result.title == "Test Video"
        assert result.media_type == "youtube"
        assert result.local_path == fake_audio
        assert result.metadata["duration"] == 300
        assert result.metadata["channel"] == "Test Channel"

    def test_import_error(self, tmp_path):
        """yt-dlp not installed should return error message."""
        with patch.dict(sys.modules, {"yt_dlp": None}):
            # Force ImportError by removing from sys.modules
            saved = sys.modules.pop("yt_dlp", None)
            try:
                # We need to trigger the ImportError inside the function
                # Since we can't easily remove it from sys.modules during import,
                # let's test the fallback path
                pass
            finally:
                if saved is not None:
                    sys.modules["yt_dlp"] = saved

        # Test via patching the import mechanism
        with patch("builtins.__import__", side_effect=ImportError("no yt_dlp")):
            result = download_youtube("https://youtube.com/watch?v=test", tmp_path)
        assert result.error is not None
        assert "yt-dlp" in result.error

    def test_download_error(self, tmp_path):
        """Download failure should return error message."""
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.side_effect = Exception("Network error")
        mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
        mock_ydl_instance.__exit__ = MagicMock(return_value=False)

        mock_yt_dlp = MagicMock()
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl_instance

        with patch.dict(sys.modules, {"yt_dlp": mock_yt_dlp}):
            result = download_youtube("https://youtube.com/watch?v=fail", tmp_path)

        assert result.error is not None
        assert "Network error" in result.error

    def test_no_info_returned(self, tmp_path):
        """extract_info returning None should be handled gracefully."""
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.return_value = None
        mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
        mock_ydl_instance.__exit__ = MagicMock(return_value=False)

        mock_yt_dlp = MagicMock()
        mock_yt_dlp.YoutubeDL.return_value = mock_ydl_instance

        with patch.dict(sys.modules, {"yt_dlp": mock_yt_dlp}):
            result = download_youtube("https://youtube.com/watch?v=none", tmp_path)

        assert result.error is not None


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------

class TestDownloadPdf:
    def test_success(self, tmp_path):
        """Mock pdfplumber + urllib to simulate successful PDF extraction."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page 1 content here"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b"%PDF-fake"

        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}), \
             patch("core.media_downloader.urllib.request.urlopen", return_value=mock_response), \
             patch("core.media_downloader.shutil.copyfileobj"):
            # Create the fake PDF file so pdfplumber.open doesn't fail on missing file
            (tmp_path / "document.pdf").write_bytes(b"%PDF-fake")
            result = download_pdf("https://example.com/paper.pdf", tmp_path)

        assert result.error is None
        assert result.media_type == "pdf"
        assert result.text_content == "Page 1 content here"
        assert result.metadata["page_count"] == 1

    def test_import_error(self, tmp_path):
        """pdfplumber not installed should return error message."""
        with patch("builtins.__import__", side_effect=ImportError("no pdfplumber")):
            result = download_pdf("https://example.com/paper.pdf", tmp_path)

        assert result.error is not None
        assert "pdfplumber" in result.error

    def test_network_error(self, tmp_path):
        """Network failure should return error message."""
        import urllib.error

        mock_pdfplumber = MagicMock()

        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}), \
             patch("core.media_downloader.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")):
            result = download_pdf("https://example.com/paper.pdf", tmp_path)

        assert result.error is not None
        assert "Download failed" in result.error


# ---------------------------------------------------------------------------
# download_podcast
# ---------------------------------------------------------------------------

class TestDownloadPodcast:
    def test_success(self, tmp_path):
        """Mock urllib to simulate successful podcast download."""
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("core.media_downloader.urllib.request.urlopen", return_value=mock_response), \
             patch("core.media_downloader.shutil.copyfileobj"):
            # Create the fake audio file
            (tmp_path / "audio.mp3").write_bytes(b"fake audio")
            result = download_podcast("https://example.com/episode.mp3", tmp_path)

        assert result.error is None
        assert result.media_type == "podcast"
        assert result.local_path is not None

    def test_network_error(self, tmp_path):
        """Network failure should return error message."""
        import urllib.error

        with patch("core.media_downloader.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Timeout")):
            result = download_podcast("https://example.com/episode.mp3", tmp_path)

        assert result.error is not None
        assert "Download failed" in result.error

    def test_title_from_url(self, tmp_path):
        """Title should be extracted from the URL filename."""
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("core.media_downloader.urllib.request.urlopen", return_value=mock_response), \
             patch("core.media_downloader.shutil.copyfileobj"):
            (tmp_path / "audio.mp3").write_bytes(b"fake")
            result = download_podcast("https://example.com/my-great-episode.mp3", tmp_path)

        assert result.title == "my-great-episode"


# ---------------------------------------------------------------------------
# download_media (orchestrator)
# ---------------------------------------------------------------------------

class TestDownloadMedia:
    def test_dispatches_youtube(self, tmp_path):
        """download_media should call download_youtube for YouTube URLs."""
        with patch("core.media_downloader.download_youtube") as mock_yt:
            mock_yt.return_value = MediaContent(
                url="https://youtube.com/watch?v=test",
                title="Test",
                media_type="youtube",
            )
            result = download_media("https://youtube.com/watch?v=test", tmp_path)

        mock_yt.assert_called_once_with("https://youtube.com/watch?v=test", tmp_path)
        assert result.media_type == "youtube"

    def test_dispatches_pdf(self, tmp_path):
        """download_media should call download_pdf for PDF URLs."""
        with patch("core.media_downloader.download_pdf") as mock_pdf:
            mock_pdf.return_value = MediaContent(
                url="https://example.com/doc.pdf",
                title="doc",
                media_type="pdf",
            )
            result = download_media("https://example.com/doc.pdf", tmp_path)

        mock_pdf.assert_called_once_with("https://example.com/doc.pdf", tmp_path)
        assert result.media_type == "pdf"

    def test_dispatches_podcast(self, tmp_path):
        """download_media should call download_podcast for audio URLs."""
        with patch("core.media_downloader.download_podcast") as mock_pod:
            mock_pod.return_value = MediaContent(
                url="https://example.com/ep.mp3",
                title="ep",
                media_type="podcast",
            )
            result = download_media("https://example.com/ep.mp3", tmp_path)

        mock_pod.assert_called_once_with("https://example.com/ep.mp3", tmp_path)
        assert result.media_type == "podcast"

    def test_unknown_url(self, tmp_path):
        """download_media should return error for unknown media types."""
        result = download_media("https://example.com/article", tmp_path)

        assert result.error is not None
        assert "Unsupported" in result.error
        assert result.media_type == "unknown"

    def test_creates_tempdir_when_none(self):
        """download_media should create a temp dir if output_dir is None."""
        with patch("core.media_downloader.download_youtube") as mock_yt, \
             patch("core.media_downloader.tempfile.mkdtemp", return_value="/tmp/brain-media-test"):
            mock_yt.return_value = MediaContent(
                url="https://youtube.com/watch?v=x",
                title="X",
                media_type="youtube",
            )
            result = download_media("https://youtube.com/watch?v=x")

        assert result.media_type == "youtube"


# ---------------------------------------------------------------------------
# MediaContent dataclass
# ---------------------------------------------------------------------------

class TestMediaContent:
    def test_defaults(self):
        mc = MediaContent(url="https://x.com", title="X", media_type="youtube")
        assert mc.local_path is None
        assert mc.text_content is None
        assert mc.metadata == {}
        assert mc.error is None

    def test_with_error(self):
        mc = MediaContent(url="u", title="t", media_type="pdf", error="fail")
        assert mc.error == "fail"

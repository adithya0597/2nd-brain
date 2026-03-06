"""Tests for core/article_fetcher.py — URL extraction and article fetching."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))


from core.article_fetcher import (
    ArticleContent,
    _TextExtractor,
    extract_urls,
    fetch_article,
)


# ---------------------------------------------------------------------------
# extract_urls
# ---------------------------------------------------------------------------


class TestExtractUrls:

    def test_finds_plain_urls(self):
        text = "Check out https://example.com/article and also http://test.org/page"
        urls = extract_urls(text)
        assert "https://example.com/article" in urls
        assert "http://test.org/page" in urls

    def test_handles_slack_formatted_urls(self):
        text = "Read this: <https://example.com/post|Example Post>"
        urls = extract_urls(text)
        assert urls == ["https://example.com/post"]

    def test_handles_slack_urls_without_label(self):
        text = "Link: <https://example.com/bare>"
        urls = extract_urls(text)
        assert urls == ["https://example.com/bare"]

    def test_skips_slack_internal_domains(self):
        text = (
            "Check <https://slack.com/help> and "
            "<https://files.slack-files.com/abc> and "
            "https://example.com/real"
        )
        urls = extract_urls(text)
        assert len(urls) == 1
        assert urls[0] == "https://example.com/real"

    def test_deduplicates_urls(self):
        text = (
            "See https://example.com/page and also https://example.com/page again"
        )
        urls = extract_urls(text)
        assert urls == ["https://example.com/page"]

    def test_empty_text_returns_empty(self):
        assert extract_urls("") == []

    def test_no_urls_returns_empty(self):
        assert extract_urls("Just some regular text with no links") == []

    def test_mixed_slack_and_plain_urls(self):
        text = "<https://one.com|One> and https://two.com/path"
        urls = extract_urls(text)
        assert "https://one.com" in urls
        assert "https://two.com/path" in urls


# ---------------------------------------------------------------------------
# _TextExtractor
# ---------------------------------------------------------------------------


class TestTextExtractor:

    def test_extracts_text_from_simple_html(self):
        html = "<html><body><p>Hello world</p><p>Second paragraph</p></body></html>"
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        assert "Hello world" in text
        assert "Second paragraph" in text

    def test_strips_script_and_style_tags(self):
        html = (
            "<html><body>"
            "<script>var x = 1;</script>"
            "<style>.a { color: red; }</style>"
            "<p>Visible content</p>"
            "</body></html>"
        )
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        assert "Visible content" in text
        assert "var x = 1" not in text
        assert "color: red" not in text

    def test_strips_nav_header_footer_aside(self):
        html = (
            "<html><body>"
            "<nav>Nav links</nav>"
            "<header>Site header</header>"
            "<main><p>Main content</p></main>"
            "<footer>Footer text</footer>"
            "<aside>Sidebar</aside>"
            "</body></html>"
        )
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        assert "Main content" in text
        assert "Nav links" not in text
        assert "Site header" not in text
        assert "Footer text" not in text
        assert "Sidebar" not in text

    def test_extracts_title_tag(self):
        html = "<html><head><title>My Article Title</title></head><body><p>Content</p></body></html>"
        extractor = _TextExtractor()
        extractor.feed(html)
        assert extractor.title == "My Article Title"

    def test_adds_newlines_for_block_elements(self):
        html = "<h1>Heading</h1><p>Paragraph</p><div>Block</div>"
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        # Block elements should create newline separation
        assert "\n" in text

    def test_collapses_excessive_whitespace(self):
        html = "<p>Word1</p><p></p><p></p><p></p><p></p><p>Word2</p>"
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in text


# ---------------------------------------------------------------------------
# fetch_article (mocked)
# ---------------------------------------------------------------------------


class TestFetchArticle:

    def test_returns_none_for_unreachable_url(self):
        """fetch_article returns None when the URL cannot be fetched."""
        import urllib.error

        with patch("core.article_fetcher.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            result = fetch_article("https://nonexistent.example.com/page")
            assert result is None

    def test_returns_article_content_on_success(self):
        """fetch_article returns ArticleContent when HTML is fetched successfully."""
        html_bytes = (
            b"<html><head><title>Test Title</title></head>"
            b"<body><p>" + b"This is article content. " * 10 + b"</p></body></html>"
        )

        mock_response = MagicMock()
        mock_response.read.return_value = html_bytes
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "text/html; charset=utf-8"
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("core.article_fetcher.urllib.request.urlopen", return_value=mock_response):
            result = fetch_article("https://example.com/article")
            assert result is not None
            assert isinstance(result, ArticleContent)
            assert result.title == "Test Title"
            assert result.url == "https://example.com/article"
            assert "This is article content" in result.content
            assert result.length > 0

    def test_returns_none_for_non_html_content(self):
        """fetch_article returns None for non-HTML content types."""
        mock_response = MagicMock()
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "application/pdf"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("core.article_fetcher.urllib.request.urlopen", return_value=mock_response):
            result = fetch_article("https://example.com/file.pdf")
            assert result is None

    def test_returns_none_for_too_short_content(self):
        """fetch_article returns None if extracted text is under 50 chars."""
        html_bytes = b"<html><body><p>Hi</p></body></html>"

        mock_response = MagicMock()
        mock_response.read.return_value = html_bytes
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "text/html"
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("core.article_fetcher.urllib.request.urlopen", return_value=mock_response):
            result = fetch_article("https://example.com/short")
            assert result is None


# ---------------------------------------------------------------------------
# create_web_clip (vault_ops integration)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_config(mock_config):
    """Every test in this class uses the mock config."""
    yield


import core.vault_ops as vault_ops


class TestCreateWebClip:

    def test_creates_file_with_correct_frontmatter(self, temp_vault):
        path = vault_ops.create_web_clip(
            url="https://example.com/article",
            title="Test Article",
            summary="This is a summary of the article.",
            icor_elements=["Mind & Growth"],
            key_concepts=["concept-a", "concept-b"],
            content_preview="Full article text here...",
        )
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "type: web_clip" in content
        assert 'url: "https://example.com/article"' in content
        assert 'title: "Test Article"' in content
        assert "Mind & Growth" in content
        assert "concept-a" in content
        assert "concept-b" in content
        assert "## Summary" in content
        assert "This is a summary of the article." in content
        assert "## Content Preview" in content
        assert "Full article text here..." in content
        assert "# Test Article" in content
        assert "**Source:** https://example.com/article" in content

    def test_handles_filename_collision(self, temp_vault):
        path1 = vault_ops.create_web_clip(
            url="https://example.com/first",
            title="Same Title",
            summary="First article",
        )
        path2 = vault_ops.create_web_clip(
            url="https://example.com/second",
            title="Same Title",
            summary="Second article",
        )
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()
        # The second file should have a counter suffix
        assert "-1" in path2.stem

    def test_creates_resources_directory(self, temp_vault):
        # Resources dir should be created automatically
        resources_dir = temp_vault / "Resources"
        if resources_dir.exists():
            resources_dir.rmdir()

        path = vault_ops.create_web_clip(
            url="https://example.com/new",
            title="New Article",
            summary="A summary",
        )
        assert path.exists()
        assert path.parent.name == "Resources"

    def test_adds_daily_note_reference(self, temp_vault):
        vault_ops.ensure_daily_note()
        vault_ops.create_web_clip(
            url="https://example.com/ref",
            title="Referenced Article",
            summary="A summary",
        )
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        daily_content = (temp_vault / "Daily Notes" / f"{today}.md").read_text(encoding="utf-8")
        assert "Referenced Article" in daily_content
        assert "Resources/" in daily_content

    def test_no_summary_no_concepts(self, temp_vault):
        path = vault_ops.create_web_clip(
            url="https://example.com/minimal",
            title="Minimal Clip",
            summary="",
        )
        content = path.read_text(encoding="utf-8")
        assert "## Summary" not in content
        assert "## Key Concepts" not in content
        assert "# Minimal Clip" in content

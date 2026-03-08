"""Article fetching and extraction using only stdlib."""
import html.parser
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(
    r'<(https?://[^>|]+)(?:\|[^>]*)?>|'  # Slack-formatted URLs: <url|text> or <url>
    r'(https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}'
    r'\b[-a-zA-Z0-9()@:%_+.~#?&/=]*)'  # Plain URLs
)

# Domains to skip (not articles)
_SKIP_DOMAINS = {"slack.com", "slack-files.com", "slack-edge.com", "slack-imgs.com"}

FETCH_TIMEOUT = 10
MAX_CONTENT_LENGTH = 50000


@dataclass
class ArticleContent:
    url: str
    title: str
    content: str  # Plain text extracted from HTML
    length: int


class _TextExtractor(html.parser.HTMLParser):
    """Simple HTML to text extractor."""

    def __init__(self):
        super().__init__()
        self.result: list[str] = []
        self.title = ""
        self._in_title = False
        self._skip_tags = {"script", "style", "nav", "header", "footer", "aside"}
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "li", "tr"):
            self.result.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        if self._skip_depth == 0:
            self.result.append(data)

    def get_text(self) -> str:
        text = "".join(self.result)
        # Collapse whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()


def extract_urls(text: str) -> list[str]:
    """Extract HTTP(S) URLs from text, handling Slack URL formatting."""
    urls = []
    for match in URL_PATTERN.finditer(text):
        url = match.group(1) or match.group(2)
        if url:
            # Skip Slack internal URLs
            domain = urlparse(url).netloc.lower()
            if not any(skip in domain for skip in _SKIP_DOMAINS):
                urls.append(url)
    return list(dict.fromkeys(urls))  # Deduplicate preserving order


def fetch_article(url: str) -> ArticleContent | None:
    """Fetch and extract article content from URL using stdlib only.

    Returns ArticleContent on success, None on failure.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SecondBrain/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as response:
            # Check content type
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type and "text" not in content_type:
                logger.info("Skipping non-HTML URL: %s (%s)", url, content_type)
                return None

            raw = response.read(MAX_CONTENT_LENGTH)
            charset = response.headers.get_content_charset() or "utf-8"
            html_text = raw.decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None
    except Exception as e:
        logger.warning("Unexpected error fetching %s: %s", url, e)
        return None

    # Extract text
    extractor = _TextExtractor()
    try:
        extractor.feed(html_text)
    except Exception:
        logger.warning("HTML parsing failed for %s", url)
        return None

    content = extractor.get_text()
    title = extractor.title or url.split("/")[-1][:60]

    if len(content) < 50:
        logger.info("Extracted content too short for %s (%d chars)", url, len(content))
        return None

    return ArticleContent(
        url=url,
        title=title,
        content=content[:MAX_CONTENT_LENGTH],
        length=len(content),
    )

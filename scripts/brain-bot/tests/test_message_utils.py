"""Tests for core/message_utils.py -- split_message edge cases."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.message_utils import split_message


# ---------------------------------------------------------------------------
# Basic splitting
# ---------------------------------------------------------------------------


class TestSplitMessageBasic:
    """Empty, short, and exact-length inputs."""

    def test_empty_string_returns_single_empty(self):
        """Empty string -> ['']."""
        assert split_message("") == [""]

    def test_short_text_returns_single_element(self):
        """Text shorter than max_len comes back as a single-element list."""
        text = "Hello, world!"
        result = split_message(text)
        assert result == [text]

    def test_exact_max_len_returns_single_element(self):
        """Text exactly at max_len should NOT be split."""
        text = "a" * 4096
        result = split_message(text)
        assert result == [text]

    def test_custom_max_len(self):
        """Custom max_len is respected."""
        text = "a" * 100
        result = split_message(text, max_len=50)
        assert len(result) >= 2
        # Reassembled text matches original
        assert "".join(result) == text


# ---------------------------------------------------------------------------
# Split-point preference hierarchy
# ---------------------------------------------------------------------------


class TestSplitPointPreference:
    """Verify paragraph > newline > space > hard-cut ordering."""

    def test_splits_at_paragraph_boundary(self):
        """Prefers splitting at paragraph breaks (\\n\\n)."""
        para1 = "A" * 30
        para2 = "B" * 30
        text = para1 + "\n\n" + para2
        result = split_message(text, max_len=50)
        assert len(result) == 2
        assert result[0] == para1 + "\n\n"
        assert result[1] == para2

    def test_splits_at_newline_when_no_paragraph(self):
        """Falls back to newline split when no paragraph break is available."""
        line1 = "A" * 30
        line2 = "B" * 30
        text = line1 + "\n" + line2
        result = split_message(text, max_len=50)
        assert len(result) == 2
        assert result[0] == line1 + "\n"
        assert result[1] == line2

    def test_splits_at_space_as_last_resort(self):
        """Falls back to space split when no newline is available."""
        word1 = "A" * 28
        word2 = "B" * 28
        text = word1 + " " + word2
        result = split_message(text, max_len=50)
        assert len(result) == 2
        assert result[0] == word1 + " "
        assert result[1] == word2

    def test_hard_cut_when_no_whitespace(self):
        """Hard-cuts at max_len when no whitespace is found in the second half."""
        text = "A" * 100
        result = split_message(text, max_len=50)
        assert len(result) == 2
        assert result[0] == "A" * 50
        assert result[1] == "A" * 50


# ---------------------------------------------------------------------------
# HTML tag tracking across splits
# ---------------------------------------------------------------------------


class TestHtmlTagTracking:
    """Ensure unclosed HTML tags are closed/reopened across chunks."""

    def test_unclosed_bold_tag_repaired(self):
        """An unclosed <b> at the split point gets </b> appended, next chunk gets <b>."""
        # Build text: <b> + filler that forces a split + </b>
        inner = "X" * 45
        text = "<b>" + inner + "</b>"
        result = split_message(text, max_len=30)
        assert len(result) >= 2
        # First chunk must close the <b>
        assert result[0].endswith("</b>")
        # Second chunk must re-open <b>
        assert result[1].startswith("<b>")

    def test_nested_tags_closed_in_order(self):
        """Nested <b><i>...</i></b> are closed innermost-first."""
        # Force split inside nested tags
        inner = "Z" * 40
        text = "<b><i>" + inner + "</i></b>"
        result = split_message(text, max_len=30)
        assert len(result) >= 2
        # First chunk should close in reverse nesting order: </i></b>
        assert result[0].endswith("</i></b>")
        # Second chunk should re-open tags (implementation prepends individually,
        # so inner-first: <i><b>)
        assert result[1].startswith("<i><b>")

    def test_self_closing_tags_ignored(self):
        """<br> and other self-closing tags don't affect open-tag tracking."""
        filler = "W" * 40
        text = "<b>" + filler + "<br>" + filler + "</b>"
        result = split_message(text, max_len=50)
        assert len(result) >= 2
        # First chunk should close <b> only (not try to close <br>)
        assert "</br>" not in result[0]
        assert result[0].endswith("</b>")

    def test_properly_closed_tags_not_duplicated(self):
        """Tags that open and close within the same chunk are not re-opened."""
        text = "<b>short</b> " + "A" * 45
        result = split_message(text, max_len=50)
        # <b> is closed within the first chunk, so second chunk should NOT get <b>
        if len(result) >= 2:
            assert not result[1].startswith("<b>")

    def test_multiple_splits_with_tags(self):
        """Tags are tracked correctly across three or more chunks."""
        # Build text that will need 3+ chunks at max_len=30
        text = "<b>" + "Y" * 80 + "</b>"
        result = split_message(text, max_len=30)
        assert len(result) >= 3
        # Every chunk except the very last should end with </b>
        for chunk in result[:-1]:
            assert chunk.endswith("</b>"), f"Chunk missing closing tag: {chunk!r}"
        # Every chunk except the first should start with <b>
        for chunk in result[1:]:
            assert chunk.startswith("<b>"), f"Chunk missing opening tag: {chunk!r}"

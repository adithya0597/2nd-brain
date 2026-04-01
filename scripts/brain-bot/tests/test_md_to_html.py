"""Tests for core.md_to_html — markdown conversion and vault cleanup."""
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("config", MagicMock())

from core.md_to_html import clean_for_vault, md_to_telegram_html


class TestMdToTelegramHtml:
    def test_empty_string(self):
        assert md_to_telegram_html("") == ""

    def test_bold_converted(self):
        result = md_to_telegram_html("**hello**")
        assert "<b>" in result
        assert "hello" in result

    def test_italic_converted(self):
        result = md_to_telegram_html("*italic*")
        assert "<i>" in result
        assert "italic" in result

    def test_special_chars_safe(self):
        # Should not crash with HTML special chars
        result = md_to_telegram_html("5 > 3 & 2 < 4")
        assert result  # Should produce non-empty output

    def test_headers_converted(self):
        result = md_to_telegram_html("## Section Title")
        assert "Section Title" in result

    def test_list_items(self):
        result = md_to_telegram_html("- item one\n- item two")
        assert "item one" in result
        assert "item two" in result

    def test_code_inline(self):
        result = md_to_telegram_html("Use `print()` here")
        assert "<code>" in result

    def test_none_returns_none(self):
        assert md_to_telegram_html(None) is None


class TestCleanForVault:
    def test_empty_string(self):
        assert clean_for_vault("") == ""

    def test_strips_preamble_heres_your(self):
        text = "Here's your morning briefing:\n## Today's Plan\n- item 1"
        result = clean_for_vault(text)
        assert result.startswith("## Today's Plan")

    def test_strips_preamble_sure(self):
        text = "Sure! Here's the analysis:\n## Analysis\nContent here"
        result = clean_for_vault(text)
        assert result.startswith("## Analysis")

    def test_strips_postamble_let_me_know(self):
        text = "## Report\nContent here\n\nLet me know if you need anything else!"
        result = clean_for_vault(text)
        assert "Let me know" not in result
        assert "## Report" in result

    def test_strips_postamble_feel_free(self):
        text = "## Report\nContent\n\nFeel free to ask if you have questions."
        result = clean_for_vault(text)
        assert "Feel free" not in result

    def test_strips_code_fence_wrapper(self):
        text = "```markdown\n## Report\nContent here\n```"
        result = clean_for_vault(text)
        assert result == "## Report\nContent here"

    def test_strips_md_code_fence(self):
        text = "```md\n## Title\nBody\n```"
        result = clean_for_vault(text)
        assert result == "## Title\nBody"

    def test_preserves_internal_code_fences(self):
        text = "## Report\n\n```python\nprint('hi')\n```\n\nMore content"
        result = clean_for_vault(text)
        assert "```python" in result
        assert "print('hi')" in result

    def test_combined_cleanup(self):
        text = "Sure! Here's your report:\n## Summary\nGood stuff\n\nLet me know if you want more details!"
        result = clean_for_vault(text)
        assert result.startswith("## Summary")
        assert "Let me know" not in result
        assert "Sure" not in result

    def test_none_returns_none(self):
        assert clean_for_vault(None) is None

    def test_clean_text_unchanged(self):
        text = "## Report\n\n- Item 1\n- Item 2"
        assert clean_for_vault(text) == text

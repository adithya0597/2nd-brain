"""Markdown-to-Telegram-HTML conversion and vault cleanup.

Uses chatgpt-md-converter for reliable md->Telegram HTML.
"""
import re

from chatgpt_md_converter import telegram_format


def md_to_telegram_html(text: str) -> str:
    """Convert LLM markdown output to Telegram-compatible HTML."""
    if not text:
        return text
    return telegram_format(text)


# Patterns for stripping AI narration artifacts
_PREAMBLE_RE = re.compile(
    r"^(?:(?:Sure|Okay|Alright|Absolutely|Of course|Certainly|Great)[!.,]*\s*)*"
    r"(?:Here(?:'s| is) (?:your|the|a) .{0,80}?(?::\s*\n|\n))?",
    re.IGNORECASE,
)
_POSTAMBLE_RE = re.compile(
    r"\n*(?:(?:Let me know|Feel free|Would you like|Hope this helps|Is there anything)"
    r".{0,120}?)$",
    re.IGNORECASE,
)
_CODE_FENCE_WRAP_RE = re.compile(
    r"^```(?:markdown|md)?\s*\n(.*?)\n```\s*$",
    re.DOTALL,
)


def clean_for_vault(text: str) -> str:
    """Strip AI narration artifacts before vault write."""
    if not text:
        return text
    # Strip wrapping code fences (entire response wrapped in ```)
    m = _CODE_FENCE_WRAP_RE.match(text.strip())
    if m:
        text = m.group(1)
    # Strip preamble
    text = _PREAMBLE_RE.sub("", text, count=1)
    # Strip postamble
    text = _POSTAMBLE_RE.sub("", text)
    return text.strip()

"""Tests for core/message_utils.py — message splitting and sending."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.message_utils import split_message, send_long_message


# ---------------------------------------------------------------------------
# split_message
# ---------------------------------------------------------------------------

class TestSplitMessage:
    def test_empty(self):
        assert split_message("") == [""]

    def test_short(self):
        assert split_message("Hello") == ["Hello"]

    def test_exactly_at_limit(self):
        text = "a" * 4096
        assert split_message(text) == [text]

    def test_splits_at_paragraph(self):
        # Create text with a paragraph break within first half
        first_part = "a" * 2500 + "\n\n"
        second_part = "b" * 2500
        text = first_part + second_part
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0].endswith("\n\n") or chunks[0].strip().endswith("a")

    def test_splits_at_newline(self):
        first_part = "a" * 3000 + "\n"
        second_part = "b" * 2000
        text = first_part + second_part
        chunks = split_message(text)
        assert len(chunks) == 2

    def test_splits_at_space(self):
        first_part = "word " * 800  # ~4000 chars
        second_part = "more " * 200
        text = first_part + second_part
        chunks = split_message(text)
        assert len(chunks) >= 2

    def test_handles_html_tags(self):
        # Create a long bold section spanning multiple chunks
        text = "<b>" + "a " * 2500 + "</b>" + " " + "b " * 1500
        chunks = split_message(text)
        assert len(chunks) >= 2
        # HTML tag repair should happen — verify no crash

    def test_nested_html(self):
        text = "<b><i>" + "x" * 4200 + "</i></b>"
        chunks = split_message(text)
        assert len(chunks) >= 2

    def test_self_closing_tags(self):
        text = "a" * 3000 + "<br>" + "b" * 2000
        chunks = split_message(text)
        assert len(chunks) >= 2

    def test_hard_cut_no_break_points(self):
        text = "a" * 5000  # No spaces, newlines, or paragraphs
        chunks = split_message(text)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_multiple_chunks(self):
        text = "x" * 12000
        chunks = split_message(text)
        assert len(chunks) >= 3


# ---------------------------------------------------------------------------
# send_long_message
# ---------------------------------------------------------------------------

class TestSendLongMessage:
    @pytest.mark.asyncio
    async def test_short_message(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        msgs = await send_long_message(bot, -100, "Hello")
        assert len(msgs) == 1
        bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_long_message_splits(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        text = "word " * 1000  # ~5000 chars
        msgs = await send_long_message(bot, -100, text)
        assert len(msgs) >= 2

    @pytest.mark.asyncio
    async def test_keyboard_on_last_chunk(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        text = "word " * 1000
        keyboard = MagicMock()
        msgs = await send_long_message(bot, -100, text, reply_markup=keyboard)

        # Last call should have reply_markup, earlier ones should not
        calls = bot.send_message.call_args_list
        assert len(calls) >= 2
        assert "reply_markup" not in calls[0].kwargs
        assert calls[-1].kwargs.get("reply_markup") == keyboard

    @pytest.mark.asyncio
    async def test_topic_id(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

        msgs = await send_long_message(bot, -100, "Hello", topic_id=42)
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs.get("message_thread_id") == 42

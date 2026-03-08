"""Message splitting and sending utilities for Telegram's 4096-char limit."""

import re

from telegram import Bot, InlineKeyboardMarkup


# HTML tags that are self-closing (no matching close tag needed)
_SELF_CLOSING = frozenset({"br", "hr", "img", "input"})

# Regex to find opening and closing HTML tags
_TAG_RE = re.compile(r"<(/?)(\w+)(?:\s[^>]*)?>")


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split HTML text into chunks respecting Telegram's message length limit.

    Handles:
    - Empty strings (returns [""])
    - Text <= max_len (returns single-element list)
    - Paragraph boundary splitting (\n\n preferred)
    - Tracks and repairs unclosed HTML tags across splits
    """
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Find best split point: paragraph > newline > space > hard cut
        split_at = max_len
        last_para = remaining.rfind("\n\n", 0, max_len)
        if last_para > max_len // 2:
            split_at = last_para + 2
        else:
            last_nl = remaining.rfind("\n", 0, max_len)
            if last_nl > max_len // 2:
                split_at = last_nl + 1
            else:
                last_sp = remaining.rfind(" ", 0, max_len)
                if last_sp > max_len // 2:
                    split_at = last_sp + 1

        chunk = remaining[:split_at]
        remaining = remaining[split_at:]

        # Track open HTML tags in this chunk
        open_tags: list[str] = []
        for match in _TAG_RE.finditer(chunk):
            is_closing = match.group(1) == "/"
            tag_name = match.group(2).lower()
            if tag_name in _SELF_CLOSING:
                continue
            if is_closing:
                if open_tags and open_tags[-1] == tag_name:
                    open_tags.pop()
            else:
                open_tags.append(tag_name)

        # Close unclosed tags at end of chunk, re-open at start of next
        if open_tags:
            for tag in reversed(open_tags):
                chunk += f"</{tag}>"
            for tag in open_tags:
                remaining = f"<{tag}>" + remaining

        chunks.append(chunk)

    return chunks


async def send_long_message(
    bot: Bot,
    chat_id: int | str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    topic_id: int | None = None,
    parse_mode: str = "HTML",
) -> list:
    """Split and send a long message. Keyboard attaches to last chunk only.

    Args:
        bot: Telegram Bot instance.
        chat_id: Target chat ID.
        text: HTML-formatted message text.
        reply_markup: Optional inline keyboard (attached to final chunk).
        topic_id: Optional forum/topic thread ID.
        parse_mode: Parse mode (default "HTML").

    Returns:
        List of sent Message objects.
    """
    chunks = split_message(text)
    messages = []

    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        kwargs = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
        }
        if topic_id is not None:
            kwargs["message_thread_id"] = topic_id
        if is_last and reply_markup is not None:
            kwargs["reply_markup"] = reply_markup

        msg = await bot.send_message(**kwargs)
        messages.append(msg)

    return messages

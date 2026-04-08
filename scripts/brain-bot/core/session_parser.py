"""Session parser for Claude conversation transcripts.

Supports three formats:
- JSONL: Claude Code native transcripts (from ~/.claude/projects/)
- Markdown: Exported conversation logs (## 👤 User / ## 🤖 Claude headers)
- JSON: Claude.ai bulk export (conversations.json — array of conversation objects)

Streams assistant text blocks, filters by size/content thresholds.
"""
import json
import re
from pathlib import Path
from typing import Iterator

# Markdown turn header patterns
_CLAUDE_HEADER_RE = re.compile(r"^## .*Claude", re.IGNORECASE)
_USER_HEADER_RE = re.compile(r"^## .*User", re.IGNORECASE)
_CONVERSATION_LOG_HEADER = "# Claude Conversation Log"


def parse_session(path: Path) -> Iterator[str]:
    """Stream assistant text blocks from a Claude session JSONL file."""
    with open(path, "r") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            content = obj.get("message", {}).get("content", [])
            if isinstance(content, str):
                yield content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        yield block.get("text", "")


def parse_markdown_session(path: Path) -> Iterator[str]:
    """Stream assistant text blocks from a Markdown conversation export.

    Expected format:
        ## 👤 User
        <user message>
        ## 🤖 Claude
        <assistant message>
    """
    with open(path, "r", errors="replace") as f:
        in_claude_block = False
        current_block: list[str] = []

        for line in f:
            stripped = line.rstrip("\n")

            if _CLAUDE_HEADER_RE.match(stripped):
                # Start of a new Claude block
                if current_block:
                    text = "\n".join(current_block).strip()
                    if text:
                        yield text
                    current_block = []
                in_claude_block = True
                continue

            if _USER_HEADER_RE.match(stripped):
                # End of Claude block, start of User block
                if in_claude_block and current_block:
                    text = "\n".join(current_block).strip()
                    if text:
                        yield text
                    current_block = []
                in_claude_block = False
                continue

            # Other ## headers inside a Claude block (e.g., ## Task 1) are content
            if in_claude_block:
                current_block.append(stripped)

        # Flush last block
        if in_claude_block and current_block:
            text = "\n".join(current_block).strip()
            if text:
                yield text


def is_markdown_conversation(path: Path) -> bool:
    """Check if a file is a Markdown conversation export."""
    try:
        with open(path, "r") as f:
            first_line = f.readline().strip()
        return first_line == _CONVERSATION_LOG_HEADER
    except (OSError, UnicodeDecodeError):
        return False


def parse_json_export(path: Path) -> list[dict]:
    """Parse a Claude.ai bulk export (conversations.json).

    Returns a list of conversation dicts, each with:
    - "uuid": conversation ID
    - "name": conversation title
    - "texts": list of assistant text strings
    """
    try:
        with open(path, "r", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    conversations = []
    for conv in data:
        if not isinstance(conv, dict):
            continue
        texts = []
        for msg in conv.get("chat_messages", []):
            if not isinstance(msg, dict):
                continue
            if msg.get("sender") != "assistant":
                continue
            text = msg.get("text", "")
            if text:
                texts.append(text)
        if texts:
            conversations.append({
                "uuid": conv.get("uuid", ""),
                "name": conv.get("name", ""),
                "texts": texts,
            })
    return conversations


def parse_any_session(path: Path) -> Iterator[str]:
    """Auto-detect format and stream assistant text blocks."""
    if path.suffix == ".jsonl":
        yield from parse_session(path)
    elif path.suffix == ".md" and is_markdown_conversation(path):
        yield from parse_markdown_session(path)


def should_distill(path: Path) -> bool:
    """Check if a session file is worth distilling (size + content thresholds)."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < 10_000 or size > 20_000_000:
        return False
    char_count = sum(len(text) for text in parse_any_session(path))
    return char_count > 2000


def find_session_files(base_path: Path) -> list[Path]:
    """Find all JSONL session files under the given path, newest first."""
    return sorted(
        base_path.glob("**/*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def find_markdown_session_files(base_path: Path) -> list[Path]:
    """Find Markdown conversation exports under the given path, newest first."""
    return sorted(
        base_path.glob("**/*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

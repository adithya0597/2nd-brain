"""JSONL session parser for Claude Code conversation transcripts.

Streams assistant text blocks from session files, filters by size/content
thresholds, and discovers session files under ~/.claude/projects/.
"""
import json
from pathlib import Path
from typing import Iterator


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


def should_distill(path: Path) -> bool:
    """Check if a session file is worth distilling (size + content thresholds)."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < 10_000 or size > 20_000_000:
        return False
    char_count = sum(len(text) for text in parse_session(path))
    return char_count > 2000


def find_session_files(base_path: Path) -> list[Path]:
    """Find all JSONL session files under the given path, newest first."""
    return sorted(
        base_path.glob("**/*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

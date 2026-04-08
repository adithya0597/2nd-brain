"""Tests for core.session_parser — JSONL + Markdown session file parsing."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from core.session_parser import (
    find_markdown_session_files,
    find_session_files,
    is_markdown_conversation,
    parse_any_session,
    parse_json_export,
    parse_markdown_session,
    parse_session,
    should_distill,
)


def _write_jsonl(path: Path, lines: list[dict]):
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


def test_parse_session_extracts_assistant_text(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_jsonl(session, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "hello"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer one"}]}},
        {"type": "permission-mode", "data": {}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read"},
            {"type": "text", "text": "answer two"},
        ]}},
    ])
    texts = list(parse_session(session))
    assert texts == ["answer one", "answer two"]


def test_parse_session_handles_string_content(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_jsonl(session, [
        {"type": "assistant", "message": {"content": "plain string content"}},
    ])
    texts = list(parse_session(session))
    assert texts == ["plain string content"]


def test_parse_session_skips_corrupt_lines(tmp_path):
    session = tmp_path / "session.jsonl"
    with open(session, "w") as f:
        f.write('{"type": "assistant", "message": {"content": [{"type": "text", "text": "good"}]}}\n')
        f.write("this is not json\n")
        f.write('{"type": "assistant", "message": {"content": [{"type": "text", "text": "also good"}]}}\n')
    texts = list(parse_session(session))
    assert texts == ["good", "also good"]


def test_parse_session_empty_file(tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text("")
    assert list(parse_session(session)) == []


def test_should_distill_rejects_small_file(tmp_path):
    session = tmp_path / "tiny.jsonl"
    session.write_text('{"type": "assistant", "message": {"content": "hi"}}\n')
    assert not should_distill(session)


def test_should_distill_rejects_oversized_file(tmp_path):
    session = tmp_path / "huge.jsonl"
    # Create a file > 20MB
    with open(session, "w") as f:
        f.write("x" * (20_000_001))
    assert not should_distill(session)


def test_should_distill_rejects_low_content(tmp_path):
    session = tmp_path / "lowcontent.jsonl"
    # File is >10KB but assistant text is <2000 chars
    padding = '{"type": "user", "message": {"content": "' + "x" * 500 + '"}}\n'
    with open(session, "w") as f:
        for _ in range(25):
            f.write(padding)
        f.write('{"type": "assistant", "message": {"content": [{"type": "text", "text": "short"}]}}\n')
    assert not should_distill(session)


def test_should_distill_accepts_good_session(tmp_path):
    session = tmp_path / "good.jsonl"
    long_text = "a" * 3000
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": long_text}]}},
    ]
    # Pad file to >10KB
    padding_lines = [{"type": "user", "message": {"content": "x" * 500}} for _ in range(20)]
    _write_jsonl(session, padding_lines + lines)
    assert should_distill(session)


def test_should_distill_missing_file(tmp_path):
    assert not should_distill(tmp_path / "nonexistent.jsonl")


def test_find_session_files_returns_sorted(tmp_path):
    import time

    a = tmp_path / "a.jsonl"
    a.write_text("{}\n")
    time.sleep(0.05)
    b = tmp_path / "b.jsonl"
    b.write_text("{}\n")

    result = find_session_files(tmp_path)
    assert result == [b, a]  # newest first


def test_find_session_files_nested(tmp_path):
    sub = tmp_path / "proj" / "sub"
    sub.mkdir(parents=True)
    (sub / "deep.jsonl").write_text("{}\n")
    (tmp_path / "top.jsonl").write_text("{}\n")

    result = find_session_files(tmp_path)
    assert len(result) == 2
    assert all(p.suffix == ".jsonl" for p in result)


# --- Markdown conversation parsing ---

_MD_HEADER = "# Claude Conversation Log\n\n"


def _write_md_conversation(path: Path, turns: list[tuple[str, str]]):
    """Write a Markdown conversation file with User/Claude turns."""
    lines = [_MD_HEADER]
    for role, text in turns:
        if role == "user":
            lines.append(f"## 👤 User\n\n{text}\n\n")
        else:
            lines.append(f"## 🤖 Claude\n\n{text}\n\n")
    path.write_text("".join(lines))


def test_is_markdown_conversation_true(tmp_path):
    f = tmp_path / "conv.md"
    f.write_text("# Claude Conversation Log\n\nstuff")
    assert is_markdown_conversation(f) is True


def test_is_markdown_conversation_false_wrong_header(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# My Notes\n\nstuff")
    assert is_markdown_conversation(f) is False


def test_is_markdown_conversation_false_nonexistent(tmp_path):
    assert is_markdown_conversation(tmp_path / "nope.md") is False


def test_parse_markdown_session_extracts_claude_blocks(tmp_path):
    f = tmp_path / "conv.md"
    _write_md_conversation(f, [
        ("user", "hello"),
        ("claude", "answer one"),
        ("user", "follow up"),
        ("claude", "answer two"),
    ])
    texts = list(parse_markdown_session(f))
    assert texts == ["answer one", "answer two"]


def test_parse_markdown_session_ignores_user_blocks(tmp_path):
    f = tmp_path / "conv.md"
    _write_md_conversation(f, [
        ("user", "only user text"),
    ])
    assert list(parse_markdown_session(f)) == []


def test_parse_markdown_session_preserves_internal_headers(tmp_path):
    """## headers inside a Claude block that don't match User/Claude patterns are content."""
    f = tmp_path / "conv.md"
    f.write_text(
        "# Claude Conversation Log\n\n"
        "## 🤖 Claude\n\n"
        "Here is the plan:\n\n"
        "## Task 1: Setup\n\n"
        "Do the setup.\n\n"
        "## 👤 User\n\n"
        "Thanks\n"
    )
    texts = list(parse_markdown_session(f))
    assert len(texts) == 1
    assert "Task 1: Setup" in texts[0]
    assert "Do the setup." in texts[0]


def test_parse_markdown_session_flushes_last_block(tmp_path):
    """Last Claude block (no trailing User header) is still yielded."""
    f = tmp_path / "conv.md"
    f.write_text(
        "# Claude Conversation Log\n\n"
        "## 👤 User\n\nhello\n\n"
        "## 🤖 Claude\n\nfinal answer\n"
    )
    texts = list(parse_markdown_session(f))
    assert texts == ["final answer"]


def test_parse_markdown_session_empty_blocks_skipped(tmp_path):
    f = tmp_path / "conv.md"
    f.write_text(
        "# Claude Conversation Log\n\n"
        "## 🤖 Claude\n\n"
        "## 👤 User\n\nhello\n\n"
        "## 🤖 Claude\n\nreal content\n"
    )
    texts = list(parse_markdown_session(f))
    assert texts == ["real content"]


def test_parse_any_session_routes_jsonl(tmp_path):
    session = tmp_path / "s.jsonl"
    _write_jsonl(session, [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "from jsonl"}]}},
    ])
    assert list(parse_any_session(session)) == ["from jsonl"]


def test_parse_any_session_routes_markdown(tmp_path):
    f = tmp_path / "conv.md"
    _write_md_conversation(f, [("claude", "from markdown")])
    assert list(parse_any_session(f)) == ["from markdown"]


def test_parse_any_session_skips_non_conversation_md(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# My Notes\n\nsome text")
    assert list(parse_any_session(f)) == []


def test_should_distill_accepts_markdown(tmp_path):
    """Markdown files that pass size + content thresholds are accepted."""
    f = tmp_path / "conv.md"
    long_text = "a" * 3000
    content = _MD_HEADER + f"## 🤖 Claude\n\n{long_text}\n\n"
    # Pad to >10KB
    content += "## 👤 User\n\n" + ("x" * 8000) + "\n\n"
    f.write_text(content)
    assert should_distill(f)


def test_find_markdown_session_files_returns_sorted(tmp_path):
    import time

    a = tmp_path / "a.md"
    a.write_text(_MD_HEADER + "stuff")
    time.sleep(0.05)
    b = tmp_path / "b.md"
    b.write_text(_MD_HEADER + "stuff")

    result = find_markdown_session_files(tmp_path)
    assert result[0] == b  # newest first
    assert result[1] == a


# --- JSON export parsing ---


def _sample_json_export(conversations):
    """Build a conversations.json structure."""
    return [
        {
            "uuid": c["uuid"],
            "name": c.get("name", ""),
            "chat_messages": [
                {"uuid": f"msg-{i}", "sender": m[0], "text": m[1],
                 "content": [], "created_at": "", "updated_at": "",
                 "attachments": [], "files": []}
                for i, m in enumerate(c["messages"])
            ],
        }
        for c in conversations
    ]


def test_parse_json_export_extracts_assistant_text(tmp_path):
    f = tmp_path / "conversations.json"
    data = _sample_json_export([{
        "uuid": "abc-123",
        "name": "Test conv",
        "messages": [
            ("human", "hello"),
            ("assistant", "answer one"),
            ("human", "follow up"),
            ("assistant", "answer two"),
        ],
    }])
    f.write_text(json.dumps(data))
    result = parse_json_export(f)
    assert len(result) == 1
    assert result[0]["uuid"] == "abc-123"
    assert result[0]["texts"] == ["answer one", "answer two"]


def test_parse_json_export_multiple_conversations(tmp_path):
    f = tmp_path / "conversations.json"
    data = _sample_json_export([
        {"uuid": "a", "messages": [("assistant", "text a")]},
        {"uuid": "b", "messages": [("assistant", "text b")]},
    ])
    f.write_text(json.dumps(data))
    result = parse_json_export(f)
    assert len(result) == 2


def test_parse_json_export_skips_empty_conversations(tmp_path):
    f = tmp_path / "conversations.json"
    data = _sample_json_export([
        {"uuid": "empty", "messages": [("human", "only human")]},
        {"uuid": "full", "messages": [("assistant", "has content")]},
    ])
    f.write_text(json.dumps(data))
    result = parse_json_export(f)
    assert len(result) == 1
    assert result[0]["uuid"] == "full"


def test_parse_json_export_handles_corrupt_file(tmp_path):
    f = tmp_path / "conversations.json"
    f.write_text("not json at all")
    assert parse_json_export(f) == []


def test_parse_json_export_handles_missing_file(tmp_path):
    assert parse_json_export(tmp_path / "nope.json") == []

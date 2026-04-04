"""Tests for core.session_parser — JSONL session file parsing."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from core.session_parser import find_session_files, parse_session, should_distill


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

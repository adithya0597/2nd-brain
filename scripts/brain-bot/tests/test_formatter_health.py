"""Tests for core/formatter.py — format_health_check function."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing
sys.modules.setdefault("config", MagicMock())

from core.formatter import format_health_check


# ---------------------------------------------------------------------------
# Tests for format_health_check
# ---------------------------------------------------------------------------

class TestFormatHealthCheck:

    def test_all_ok_returns_valid_blocks(self):
        checks = {
            "Database": "OK - Connected",
            "Vault": "OK - 150 files indexed",
            "Notion": "OK - Token valid",
        }
        blocks = format_health_check(checks)
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_header_block_exists(self):
        checks = {"Database": "OK"}
        blocks = format_health_check(checks)
        header_blocks = [b for b in blocks if b.get("type") == "header"]
        assert len(header_blocks) == 1
        assert "Health Check" in header_blocks[0]["text"]["text"]

    def test_each_check_gets_section_block(self):
        checks = {
            "Database": "OK",
            "Vault": "OK",
            "Scheduler": "OK",
        }
        blocks = format_health_check(checks)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        assert len(section_blocks) == 3

    def test_ok_status_gets_checkmark_emoji(self):
        checks = {"Database": "OK - Connected"}
        blocks = format_health_check(checks)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        text = section_blocks[0]["text"]["text"]
        assert ":white_check_mark:" in text

    def test_fail_status_gets_x_emoji(self):
        checks = {"Database": "FAIL - Connection refused"}
        blocks = format_health_check(checks)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        text = section_blocks[0]["text"]["text"]
        assert ":x:" in text

    def test_warn_status_gets_warning_emoji(self):
        checks = {"Notion": "WARN - Token expires soon"}
        blocks = format_health_check(checks)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        text = section_blocks[0]["text"]["text"]
        assert ":warning:" in text

    def test_mixed_statuses(self):
        checks = {
            "Database": "OK - Connected",
            "Vault": "FAIL - Not found",
            "Scheduler": "WARN - Delayed",
        }
        blocks = format_health_check(checks)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        assert len(section_blocks) == 3

        texts = [b["text"]["text"] for b in section_blocks]
        assert any(":white_check_mark:" in t for t in texts)
        assert any(":x:" in t for t in texts)
        assert any(":warning:" in t for t in texts)

    def test_empty_checks_returns_minimal_blocks(self):
        checks = {}
        blocks = format_health_check(checks)
        # Should still have header, divider, and context at minimum
        assert isinstance(blocks, list)
        assert len(blocks) >= 2  # header + context
        header_blocks = [b for b in blocks if b.get("type") == "header"]
        assert len(header_blocks) == 1

    def test_check_name_appears_in_output(self):
        checks = {"Custom Service": "OK - Running"}
        blocks = format_health_check(checks)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        text = section_blocks[0]["text"]["text"]
        assert "Custom Service" in text

    def test_context_block_with_timestamp(self):
        checks = {"Database": "OK"}
        blocks = format_health_check(checks)
        context_blocks = [b for b in blocks if b.get("type") == "context"]
        assert len(context_blocks) == 1
        text = context_blocks[0]["elements"][0]["text"]
        assert "Started at" in text

    def test_block_kit_structure_valid(self):
        checks = {"Database": "OK", "Vault": "FAIL - Missing"}
        blocks = format_health_check(checks)
        for block in blocks:
            assert "type" in block
            assert block["type"] in ("header", "section", "divider", "context", "actions")
            if block["type"] == "section":
                assert "text" in block
                assert block["text"]["type"] == "mrkdwn"

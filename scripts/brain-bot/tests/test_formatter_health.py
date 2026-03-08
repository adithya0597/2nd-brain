"""Tests for core/formatter.py — format_health_check function."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

# Mock config before importing
sys.modules.setdefault("config", MagicMock())
# Mock telegram for import
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

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
        html, keyboard = format_health_check(checks)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_header_block_exists(self):
        checks = {"Database": "OK"}
        html, keyboard = format_health_check(checks)
        assert "<b>" in html
        assert "Health Check" in html

    def test_each_check_gets_section_block(self):
        checks = {
            "Database": "OK",
            "Vault": "OK",
            "Scheduler": "OK",
        }
        html, keyboard = format_health_check(checks)
        assert "Database" in html
        assert "Vault" in html
        assert "Scheduler" in html

    def test_ok_status_gets_checkmark_emoji(self):
        checks = {"Database": "OK - Connected"}
        html, keyboard = format_health_check(checks)
        assert "\u2705" in html  # ✅

    def test_fail_status_gets_x_emoji(self):
        checks = {"Database": "FAIL - Connection refused"}
        html, keyboard = format_health_check(checks)
        assert "\u274c" in html  # ❌

    def test_warn_status_gets_warning_emoji(self):
        checks = {"Notion": "WARN - Token expires soon"}
        html, keyboard = format_health_check(checks)
        assert "\u26a0\ufe0f" in html  # ⚠️

    def test_mixed_statuses(self):
        checks = {
            "Database": "OK - Connected",
            "Vault": "FAIL - Not found",
            "Scheduler": "WARN - Delayed",
        }
        html, keyboard = format_health_check(checks)

        # All three checks present
        assert "Database" in html
        assert "Vault" in html
        assert "Scheduler" in html

        # All three emoji types present
        assert "\u2705" in html   # ✅
        assert "\u274c" in html   # ❌
        assert "\u26a0\ufe0f" in html  # ⚠️

    def test_empty_checks_returns_minimal_blocks(self):
        checks = {}
        html, keyboard = format_health_check(checks)
        # Should still have header and timestamp at minimum
        assert isinstance(html, str)
        assert "<b>" in html
        assert "Health Check" in html
        assert "Started at" in html

    def test_check_name_appears_in_output(self):
        checks = {"Custom Service": "OK - Running"}
        html, keyboard = format_health_check(checks)
        assert "Custom Service" in html

    def test_context_block_with_timestamp(self):
        checks = {"Database": "OK"}
        html, keyboard = format_health_check(checks)
        assert "Started at" in html

    def test_html_structure_valid(self):
        checks = {"Database": "OK", "Vault": "FAIL - Missing"}
        html, keyboard = format_health_check(checks)
        # Returns a string with HTML bold tags
        assert isinstance(html, str)
        assert "<b>" in html
        # Check names are wrapped in bold
        assert "<b>Database:</b>" in html or "Database" in html
        assert "<b>Vault:</b>" in html or "Vault" in html
        # Keyboard is always None for health check
        assert keyboard is None

"""Tests for core/vault_ops.py — Vault file read/write operations."""
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_config(mock_config):
    """Every test in this file uses the mock config."""
    yield


# We import after config is mocked (via autouse fixture) to keep it clean.
# However, Python caches modules so we import at module scope and rely on
# the `mock_config` fixture patching config.VAULT_PATH / DB_PATH at runtime.
import core.vault_ops as vault_ops


# ---------------------------------------------------------------------------
# ensure_daily_note
# ---------------------------------------------------------------------------

class TestEnsureDailyNote:

    def test_creates_daily_note_from_template(self, temp_vault):
        path = vault_ops.ensure_daily_note("2026-03-06")
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "2026-03-06" in content
        # Template variable replacement
        assert "Friday, March 6, 2026" in content
        assert "{{date:YYYY-MM-DD}}" not in content

    def test_idempotent_does_not_overwrite(self, temp_vault):
        path = vault_ops.ensure_daily_note("2026-03-06")
        # Write some custom content
        path.write_text("custom content", encoding="utf-8")

        # Call again — should NOT overwrite
        path2 = vault_ops.ensure_daily_note("2026-03-06")
        assert path2 == path
        assert path.read_text(encoding="utf-8") == "custom content"

    def test_creates_parent_directory(self, temp_vault):
        # Remove the Daily Notes dir
        daily_dir = temp_vault / "Daily Notes"
        daily_dir.rmdir()  # empty at this point

        path = vault_ops.ensure_daily_note("2026-01-15")
        assert path.parent.exists()

    def test_defaults_to_today(self, temp_vault):
        today = datetime.now().strftime("%Y-%m-%d")
        path = vault_ops.ensure_daily_note()
        assert path.name == f"{today}.md"


# ---------------------------------------------------------------------------
# append_to_daily_note
# ---------------------------------------------------------------------------

class TestAppendToDailyNote:

    def test_append_to_end(self, temp_vault):
        vault_ops.ensure_daily_note("2026-03-06")
        result = vault_ops.append_to_daily_note("2026-03-06", "New content here")
        assert result is True

        content = (temp_vault / "Daily Notes" / "2026-03-06.md").read_text(encoding="utf-8")
        assert "New content here" in content

    def test_append_under_section(self, temp_vault):
        vault_ops.ensure_daily_note("2026-03-06")
        result = vault_ops.append_to_daily_note(
            "2026-03-06", "Morning capture line", section="## Morning"
        )
        assert result is True

        content = (temp_vault / "Daily Notes" / "2026-03-06.md").read_text(encoding="utf-8")
        lines = content.split("\n")
        # Find "## Morning" and verify content inserted right after it
        morning_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("## Morning"))
        assert lines[morning_idx + 1] == "Morning capture line"

    def test_append_under_log_section(self, temp_vault):
        vault_ops.ensure_daily_note("2026-03-06")
        result = vault_ops.append_to_daily_note(
            "2026-03-06", "- Did something", section="## Log"
        )
        assert result is True

        content = (temp_vault / "Daily Notes" / "2026-03-06.md").read_text(encoding="utf-8")
        assert "- Did something" in content

    def test_append_section_not_found_falls_back_to_end(self, temp_vault):
        vault_ops.ensure_daily_note("2026-03-06")
        result = vault_ops.append_to_daily_note(
            "2026-03-06", "Appended content", section="## Nonexistent"
        )
        assert result is True

        content = (temp_vault / "Daily Notes" / "2026-03-06.md").read_text(encoding="utf-8")
        assert content.rstrip().endswith("Appended content")

    def test_append_multiple_times(self, temp_vault):
        vault_ops.ensure_daily_note("2026-03-06")
        vault_ops.append_to_daily_note("2026-03-06", "First append")
        vault_ops.append_to_daily_note("2026-03-06", "Second append")

        content = (temp_vault / "Daily Notes" / "2026-03-06.md").read_text(encoding="utf-8")
        assert "First append" in content
        assert "Second append" in content


# ---------------------------------------------------------------------------
# create_report_file
# ---------------------------------------------------------------------------

class TestCreateReportFile:

    def test_creates_report_with_frontmatter(self, temp_vault):
        path = vault_ops.create_report_file(
            command="drift",
            content="This is the drift report body.",
            dimensions=["Health & Vitality", "Mind & Growth"],
            date="2026-03-06",
        )
        assert path.exists()
        assert path.name == "2026-03-06-drift.md"

        content = path.read_text(encoding="utf-8")
        assert "type: report" in content
        assert "command: drift" in content
        assert "date: 2026-03-06" in content
        assert "Health & Vitality" in content
        assert "Mind & Growth" in content
        assert "This is the drift report body." in content

    def test_report_without_dimensions(self, temp_vault):
        path = vault_ops.create_report_file(
            command="emerge",
            content="Pattern synthesis results.",
            date="2026-03-06",
        )
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "icor_dimensions: []" in content

    def test_report_adds_daily_note_reference(self, temp_vault):
        vault_ops.ensure_daily_note("2026-03-06")
        vault_ops.create_report_file(
            command="ideas",
            content="Ideas body.",
            date="2026-03-06",
        )
        daily_content = (temp_vault / "Daily Notes" / "2026-03-06.md").read_text(encoding="utf-8")
        assert "Reports/2026-03-06-ideas" in daily_content


# ---------------------------------------------------------------------------
# create_concept_file
# ---------------------------------------------------------------------------

class TestCreateConceptFile:

    def test_creates_concept_with_frontmatter(self, temp_vault):
        path = vault_ops.create_concept_file(
            name="Morning Routines",
            summary="A concept about establishing morning routines.",
            source_notes=["2026-03-01", "2026-03-04"],
            icor_elements=["Health & Vitality", "Systems & Environment"],
            status="seedling",
        )
        assert path.exists()
        assert path.name == "Morning-Routines.md"

        content = path.read_text(encoding="utf-8")
        assert "type: concept" in content
        assert "status: seedling" in content
        assert "# Morning Routines" in content
        assert "A concept about establishing morning routines." in content
        assert "[[Health & Vitality]]" in content
        assert "[[Systems & Environment]]" in content
        assert "## Sources" in content
        assert "[[2026-03-01]]" in content
        assert "[[2026-03-04]]" in content

    def test_concept_without_sources(self, temp_vault):
        path = vault_ops.create_concept_file(
            name="Simple Concept",
            summary="Just a summary.",
        )
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "## Sources" not in content

    def test_concept_without_icor(self, temp_vault):
        path = vault_ops.create_concept_file(
            name="No ICOR",
            summary="No dimensions.",
        )
        content = path.read_text(encoding="utf-8")
        assert "icor_elements: []" in content
        assert "Related Dimensions" not in content


# ---------------------------------------------------------------------------
# create_inbox_entry
# ---------------------------------------------------------------------------

class TestCreateInboxEntry:

    def test_creates_unique_filenames(self, temp_vault):
        path1 = vault_ops.create_inbox_entry("First capture")
        path2 = vault_ops.create_inbox_entry("Second capture")
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_inbox_frontmatter(self, temp_vault):
        path = vault_ops.create_inbox_entry(
            content="Budget review needed",
            source="slack",
            dimensions=["Wealth & Finance"],
            confidence=0.85,
            method="keyword",
        )
        content = path.read_text(encoding="utf-8")
        assert "type: inbox" in content
        assert "source: slack" in content
        assert "status: routed" in content
        assert "Wealth & Finance" in content
        assert "confidence: 0.85" in content
        assert "classification_method: keyword" in content

    def test_inbox_unrouted_status(self, temp_vault):
        path = vault_ops.create_inbox_entry(
            content="Random thought",
            source="slack",
        )
        content = path.read_text(encoding="utf-8")
        assert "status: unprocessed" in content
        assert "icor_dimensions: []" in content


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------

class TestSanitizeFilename:

    def test_removes_path_traversal(self):
        assert ".." not in vault_ops._sanitize_filename("../../etc/passwd")

    def test_replaces_slashes(self):
        result = vault_ops._sanitize_filename("path/to\\file")
        assert "/" not in result
        assert "\\" not in result

    def test_removes_special_chars(self):
        result = vault_ops._sanitize_filename('file"name\'with?special<chars>and|pipes')
        assert '"' not in result
        assert "'" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_collapses_hyphens(self):
        result = vault_ops._sanitize_filename("too   many---hyphens   here")
        assert "---" not in result
        assert "   " not in result

    def test_empty_string_returns_untitled(self):
        assert vault_ops._sanitize_filename("") == "untitled"

    def test_only_special_chars_returns_untitled(self):
        assert vault_ops._sanitize_filename("????") == "untitled"

    def test_normal_name_passes_through(self):
        result = vault_ops._sanitize_filename("My Concept Name")
        assert result == "My-Concept-Name"


# ---------------------------------------------------------------------------
# _guard_vault_path
# ---------------------------------------------------------------------------

class TestGuardVaultPath:

    def test_valid_path_passes(self, temp_vault):
        # Should not raise
        vault_ops._guard_vault_path(temp_vault / "Reports" / "test.md")

    def test_path_traversal_blocked(self, temp_vault):
        with pytest.raises(ValueError, match="Path traversal blocked"):
            vault_ops._guard_vault_path(temp_vault / ".." / ".." / "etc" / "passwd")

    def test_absolute_escape_blocked(self, temp_vault):
        with pytest.raises(ValueError, match="Path traversal blocked"):
            vault_ops._guard_vault_path(Path("/tmp/evil.md"))


# ---------------------------------------------------------------------------
# format_capture_line
# ---------------------------------------------------------------------------

class TestFormatCaptureLine:

    def test_basic_capture(self):
        line = vault_ops.format_capture_line("Test message", ["Health & Vitality"])
        assert "**[Slack Capture]**" in line
        assert "Test message" in line
        assert "[[Health & Vitality]]" in line
        assert "#capture" in line

    def test_action_capture(self):
        line = vault_ops.format_capture_line(
            "Need to call doctor",
            ["Health & Vitality"],
            is_action=True,
        )
        assert "**[Action]**" in line
        assert "- [ ]" in line
        assert "#action" in line

    def test_no_dimensions(self):
        line = vault_ops.format_capture_line("Uncategorized thought")
        assert "Uncategorized" in line

"""Tests for core.quality_gate — LLM content validation."""
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def vault_path(tmp_path):
    """Create a minimal vault structure for wikilink validation."""
    dims = tmp_path / "Dimensions"
    dims.mkdir()
    (dims / "Health & Vitality.md").write_text("# Health")
    concepts = tmp_path / "Concepts"
    concepts.mkdir()
    (concepts / "Test-Concept.md").write_text("# Test")
    return tmp_path


def test_valid_content_passes(vault_path):
    """Well-formed content with valid links passes the gate."""
    with patch("core.quality_gate.config") as mock_config:
        mock_config.VAULT_PATH = vault_path
        from core.quality_gate import validate_vault_write

        content = """---
type: inbox
date: 2026-04-01
---

A note about [[Health & Vitality]] and [[Test-Concept]].
"""
        issues = validate_vault_write(content, vault_path / "test.md")
        assert issues == []


def test_broken_wikilink_detected(vault_path):
    """Broken wikilinks are flagged."""
    with patch("core.quality_gate.config") as mock_config:
        mock_config.VAULT_PATH = vault_path
        from core.quality_gate import validate_vault_write

        content = "Check out [[Nonexistent Page]] for details."
        issues = validate_vault_write(content, vault_path / "test.md")
        assert any("Broken wikilink" in i for i in issues)


def test_invalid_yaml_detected(vault_path):
    """Invalid YAML frontmatter is flagged."""
    with patch("core.quality_gate.config") as mock_config:
        mock_config.VAULT_PATH = vault_path
        from core.quality_gate import validate_vault_write

        content = "---\ninvalid: [unclosed\n---\nBody text."
        issues = validate_vault_write(content, vault_path / "test.md")
        assert any("Invalid YAML" in i for i in issues)


def test_long_content_flagged(vault_path):
    """Suspiciously long content is flagged."""
    with patch("core.quality_gate.config") as mock_config:
        mock_config.VAULT_PATH = vault_path
        from core.quality_gate import validate_vault_write

        content = " ".join(["word"] * 2500)
        issues = validate_vault_write(content, vault_path / "test.md")
        assert any("Suspiciously long" in i for i in issues)


def test_display_text_wikilinks_handled(vault_path):
    """Wikilinks with display text (e.g. [[path|display]]) resolve correctly."""
    with patch("core.quality_gate.config") as mock_config:
        mock_config.VAULT_PATH = vault_path
        from core.quality_gate import validate_vault_write

        content = "See [[Test-Concept|my concept]] for details."
        issues = validate_vault_write(content, vault_path / "test.md")
        assert issues == []

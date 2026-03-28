"""Tests for core.rolling_memo — daily structured append to vault file."""
from pathlib import Path
from unittest.mock import patch

import pytest


SAMPLE_MEMO = """### 2026-03-28

**Mood/Energy**: good / high
**ICOR Active**: Mind & Growth, Systems & Environment
**Key Themes**:
- Graph memory research
- Adversarial review via grill skill
**Decisions Made**: Ship CG first per grill recommendation
**Open Thread**: Will concept graduation produce useful proposals?
**Carry Forward**: Observe first graduation proposal on Sunday
"""

SAMPLE_MEMO_DAY2 = """### 2026-03-29

**Mood/Energy**: okay / medium
**ICOR Active**: Mind & Growth
**Key Themes**:
- Rolling memo implementation
**Decisions Made**: none
**Open Thread**: Same as yesterday
**Carry Forward**: Monitor kill criteria
"""


@pytest.fixture
def memo_env(tmp_path):
    """Set up a temporary memo path and patch _on_vault_write."""
    reports = tmp_path / "Reports"
    reports.mkdir()
    memo_path = reports / "rolling-memo.md"

    import core.rolling_memo as mod
    original = mod.MEMO_PATH
    mod.MEMO_PATH = memo_path
    yield mod, memo_path
    mod.MEMO_PATH = original


class TestAppendToRollingMemo:

    def test_creates_file_on_first_write(self, memo_env):
        mod, memo_path = memo_env
        with patch("core.vault_ops._on_vault_write"):
            result = mod.append_to_rolling_memo(SAMPLE_MEMO, "2026-03-28")
            assert result is True
            content = memo_path.read_text()
            assert "type: rolling-memo" in content
            assert "source: system" in content
            assert "### 2026-03-28" in content
            assert "Graph memory research" in content

    def test_appends_without_overwriting(self, memo_env):
        mod, memo_path = memo_env
        with patch("core.vault_ops._on_vault_write"):
            mod.append_to_rolling_memo(SAMPLE_MEMO, "2026-03-28")
            mod.append_to_rolling_memo(SAMPLE_MEMO_DAY2, "2026-03-29")

            content = memo_path.read_text()
            assert "### 2026-03-28" in content
            assert "### 2026-03-29" in content
            assert "Graph memory research" in content
            assert "Rolling memo implementation" in content

    def test_dedup_same_day(self, memo_env):
        mod, memo_path = memo_env
        with patch("core.vault_ops._on_vault_write"):
            mod.append_to_rolling_memo(SAMPLE_MEMO, "2026-03-28")
            first_len = len(memo_path.read_text())

            # Same day again — should skip
            mod.append_to_rolling_memo(SAMPLE_MEMO, "2026-03-28")
            second_len = len(memo_path.read_text())

            assert first_len == second_len, "Same-day append should be skipped"

    def test_frontmatter_has_provenance(self, memo_env):
        mod, memo_path = memo_env
        with patch("core.vault_ops._on_vault_write"):
            mod.append_to_rolling_memo(SAMPLE_MEMO, "2026-03-28")
            content = memo_path.read_text()
            assert "source: system" in content
            assert "type: rolling-memo" in content

    def test_returns_false_on_error(self):
        import core.rolling_memo as mod
        original = mod.MEMO_PATH
        mod.MEMO_PATH = Path("/nonexistent/impossible/path/memo.md")
        try:
            with patch("core.vault_ops._on_vault_write"):
                result = mod.append_to_rolling_memo(SAMPLE_MEMO, "2026-03-28")
                assert result is False
        finally:
            mod.MEMO_PATH = original

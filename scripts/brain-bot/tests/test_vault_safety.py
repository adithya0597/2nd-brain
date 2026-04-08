"""Tests for core.vault_safety — vault snapshot before batch operations."""
from unittest.mock import MagicMock, patch


def test_snapshot_success():
    """snapshot_vault_before_batch returns commit output on success."""
    with patch("core.vault_safety.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"abc123\n")
        from core.vault_safety import snapshot_vault_before_batch

        result = snapshot_vault_before_batch("test-batch")
        assert result == "abc123"
        assert mock_run.call_count == 2
        # First call: git add vault/
        assert mock_run.call_args_list[0][0][0] == ["git", "add", "vault/"]
        # Second call: git commit
        commit_args = mock_run.call_args_list[1][0][0]
        assert commit_args[0:2] == ["git", "commit"]
        assert "pre-test-batch snapshot" in commit_args[3]


def test_snapshot_failure_returns_empty():
    """snapshot_vault_before_batch returns empty string on git failure."""
    with patch("core.vault_safety.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stderr=b"nothing to commit"
        )
        from core.vault_safety import snapshot_vault_before_batch

        result = snapshot_vault_before_batch("test-batch")
        assert result == ""


def test_snapshot_uses_check_false():
    """subprocess.run called with check=False (never raises)."""
    with patch("core.vault_safety.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ok\n")
        from core.vault_safety import snapshot_vault_before_batch

        snapshot_vault_before_batch("x")
        for call in mock_run.call_args_list:
            assert call[1].get("check") is False

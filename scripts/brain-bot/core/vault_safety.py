"""Vault safety utilities for batch operations."""
import logging
import subprocess

import config

logger = logging.getLogger(__name__)


def snapshot_vault_before_batch(label: str) -> str:
    """Git commit vault state before batch operations.

    Returns commit hash on success, empty string on failure.
    """
    project_root = config.PROJECT_ROOT
    subprocess.run(
        ["git", "add", "vault/"],
        cwd=str(project_root),
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        ["git", "commit", "-m", f"auto: pre-{label} snapshot", "--allow-empty"],
        cwd=str(project_root),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("Vault snapshot failed: %s", result.stderr.decode())
        return ""
    return result.stdout.decode().strip()

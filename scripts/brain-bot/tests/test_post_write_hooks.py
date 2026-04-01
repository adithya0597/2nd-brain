"""Tests for the post-write hook chain in core/vault_ops.py.

The capstone criticism: "_on_vault_write is always patched out in tests."
These tests exercise the actual hook chain by temporarily unsetting
PYTEST_CURRENT_TEST and running _do_index synchronously.
"""
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure brain-bot is on sys.path (conftest handles this, but be explicit)
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))


class SyncExecutor:
    """Drop-in replacement for ThreadPoolExecutor that runs fn() synchronously.

    Eliminates race conditions in tests: _on_vault_write calls
    executor.submit(_do_index), and this makes _do_index run inline.
    """

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


@pytest.fixture()
def hook_env(test_db, temp_vault):
    """Set up config + env for post-write hook tests.

    - Points config.DB_PATH and config.VAULT_PATH at temp fixtures
    - Yields a dict with db_path and vault_path
    """
    with (
        patch("config.DB_PATH", test_db),
        patch("config.VAULT_PATH", temp_vault),
    ):
        yield {"db_path": test_db, "vault_path": temp_vault}


def _unset_pytest_env():
    """Remove PYTEST_CURRENT_TEST so _on_vault_write does not early-return."""
    return os.environ.pop("PYTEST_CURRENT_TEST", None)


def _restore_pytest_env(saved):
    """Restore PYTEST_CURRENT_TEST after the test."""
    if saved is not None:
        os.environ["PYTEST_CURRENT_TEST"] = saved


# --------------------------------------------------------------------------
# Test 1: ensure_daily_note triggers the hook
# --------------------------------------------------------------------------


def test_ensure_daily_note_calls_hook(hook_env):
    """When ensure_daily_note creates a new file, _on_vault_write fires."""
    from core.vault_ops import ensure_daily_note

    calls = []

    def spy_hook(file_path):
        calls.append(file_path)
        # Don't run the real hook (we test that separately)

    saved = _unset_pytest_env()
    try:
        with patch("core.vault_ops._on_vault_write", side_effect=spy_hook):
            path = ensure_daily_note("2099-01-15")
    finally:
        _restore_pytest_env(saved)

    assert path.exists(), "Daily note file should have been created"
    assert len(calls) == 1, f"Hook should fire exactly once, got {len(calls)}"
    assert calls[0] == path


# --------------------------------------------------------------------------
# Test 2: hook runs vault_index and FTS for real (the money test)
# --------------------------------------------------------------------------


def test_hook_runs_vault_index_and_fts(hook_env):
    """_on_vault_write indexes the file into vault_nodes and vault_fts.

    Cheap stages (vault_indexer.index_single_file, fts_index.update_single_file_fts)
    run for real against the temp DB. Expensive stages (embedding, chunk, ICOR,
    semantic similarity, graph cache) are mocked out.
    """
    vault_path = hook_env["vault_path"]
    db_path = hook_env["db_path"]

    # Create a test markdown file inside the vault (not in excluded dirs)
    test_file = vault_path / "Inbox" / "2099-01-15-test-hook.md"
    test_file.write_text(
        "---\n"
        "type: inbox\n"
        "date: 2099-01-15\n"
        "---\n"
        "\n"
        "# Test Hook Content\n"
        "\n"
        "This file tests the post-write hook chain.\n",
        encoding="utf-8",
    )

    saved = _unset_pytest_env()
    try:
        # Mock expensive stages so they don't try to load ML models
        with (
            patch("core.async_utils.executor", SyncExecutor()),
            patch("core.embedding_store.embed_single_file", return_value=None),
            patch("core.chunk_embedder.rechunk_and_embed_file", return_value=None),
            patch("core.icor_affinity.update_icor_edges_for_file", return_value=None),
            patch("core.graph_ops.update_tag_shared_edges_for_file", return_value=None),
            patch(
                "core.graph_ops.update_semantic_similarity_edges_for_file",
                return_value=None,
            ),
            patch("core.graph_cache.invalidate", return_value=None),
        ):
            from core.vault_ops import _on_vault_write

            _on_vault_write(test_file)
    finally:
        _restore_pytest_env(saved)

    # Verify vault_nodes has a row for this file
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM vault_nodes WHERE file_path = ?",
            ("Inbox/2099-01-15-test-hook.md",),
        ).fetchone()
        assert row is not None, "vault_nodes should contain the indexed file"
        assert row["title"] == "2099-01-15-test-hook"
        assert row["node_type"] == "document"

        # Verify vault_fts has content for this file
        fts_row = conn.execute(
            "SELECT * FROM vault_fts WHERE file_path = ?",
            ("Inbox/2099-01-15-test-hook.md",),
        ).fetchone()
        assert fts_row is not None, "vault_fts should contain the indexed file"
        assert "hook chain" in fts_row["content"]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Test 3: errors inside _do_index do not propagate
# --------------------------------------------------------------------------


def test_hook_errors_do_not_propagate(hook_env):
    """If index_single_file raises, the hook swallows the error.

    The remaining stages (FTS, embedding, etc.) still attempt to run.
    """
    vault_path = hook_env["vault_path"]

    # Create a minimal file so the hook has something to work with
    test_file = vault_path / "Inbox" / "2099-01-16-error-test.md"
    test_file.write_text("# Error test\n\nSome content.\n", encoding="utf-8")

    fts_called = []

    def spy_fts(fp, **kwargs):
        fts_called.append(fp)

    saved = _unset_pytest_env()
    try:
        with (
            patch("core.async_utils.executor", SyncExecutor()),
            patch(
                "core.vault_indexer.index_single_file",
                side_effect=RuntimeError("Simulated index failure"),
            ),
            patch("core.fts_index.update_single_file_fts", side_effect=spy_fts),
            patch("core.embedding_store.embed_single_file", return_value=None),
            patch("core.chunk_embedder.rechunk_and_embed_file", return_value=None),
            patch("core.icor_affinity.update_icor_edges_for_file", return_value=None),
            patch("core.graph_ops.update_tag_shared_edges_for_file", return_value=None),
            patch(
                "core.graph_ops.update_semantic_similarity_edges_for_file",
                return_value=None,
            ),
            patch("core.graph_cache.invalidate", return_value=None),
        ):
            from core.vault_ops import _on_vault_write

            # Should NOT raise, even though index_single_file blows up
            _on_vault_write(test_file)
    finally:
        _restore_pytest_env(saved)

    # FTS stage should still have been attempted after the index failure
    assert len(fts_called) == 1, "FTS update should still run after index failure"


# --------------------------------------------------------------------------
# Test 4: hook does nothing when PYTEST_CURRENT_TEST is set
# --------------------------------------------------------------------------


def test_hook_skips_when_pytest_env_set(hook_env):
    """Verify the PYTEST_CURRENT_TEST guard works as documented."""
    from core.vault_ops import _on_vault_write

    vault_path = hook_env["vault_path"]
    test_file = vault_path / "Inbox" / "2099-01-17-guard-test.md"
    test_file.write_text("# Guard test\n", encoding="utf-8")

    # PYTEST_CURRENT_TEST should already be set by pytest
    assert os.environ.get("PYTEST_CURRENT_TEST"), (
        "Expected PYTEST_CURRENT_TEST to be set during test execution"
    )

    mock_exec = MagicMock()
    with patch("core.async_utils.executor", mock_exec):
        _on_vault_write(test_file)

    mock_exec.submit.assert_not_called()

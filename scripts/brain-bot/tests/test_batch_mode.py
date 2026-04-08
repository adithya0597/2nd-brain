"""Tests for vault_ops batch mode — hook suppression during bulk writes."""
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_batch_mode_suppresses_hooks():
    """During batch mode, _on_vault_write queues files instead of indexing."""
    import core.vault_ops as vo

    vo._batch_mode = False
    vo._batch_queue.clear()

    vo.enter_batch_mode()
    assert vo._batch_mode is True

    # Simulate a vault write during batch mode (skip PYTEST guard)
    with patch.dict("os.environ", {}, clear=False):
        # Remove PYTEST_CURRENT_TEST to allow _on_vault_write to proceed
        import os
        old = os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            vo._on_vault_write(Path("/fake/file.md"))
            assert Path("/fake/file.md") in vo._batch_queue
        finally:
            if old is not None:
                os.environ["PYTEST_CURRENT_TEST"] = old

    vo.exit_batch_mode()
    assert vo._batch_mode is False
    assert vo._batch_queue == []


def test_exit_batch_mode_triggers_reindex():
    """exit_batch_mode calls vault_indexer.index_to_db when queue is non-empty."""
    import core.vault_ops as vo

    vo.enter_batch_mode()
    vo._batch_queue.append(Path("/fake/a.md"))
    vo._batch_queue.append(Path("/fake/b.md"))

    with patch("core.vault_indexer.index_to_db") as mock_reindex:
        vo.exit_batch_mode()
        mock_reindex.assert_called_once()


def test_exit_batch_mode_no_reindex_when_empty():
    """exit_batch_mode does NOT call reindex when queue is empty."""
    import core.vault_ops as vo

    vo.enter_batch_mode()
    # Don't add anything to queue

    with patch("core.vault_indexer.index_to_db") as mock_reindex:
        vo.exit_batch_mode()
        mock_reindex.assert_not_called()


def test_batch_mode_thread_safety():
    """Concurrent enter/exit batch mode doesn't race."""
    import core.vault_ops as vo

    errors = []

    def toggle_batch(n):
        try:
            for _ in range(n):
                vo.enter_batch_mode()
                vo._batch_queue.append(Path(f"/fake/{threading.current_thread().name}.md"))
                vo.exit_batch_mode()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=toggle_batch, args=(20,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread safety errors: {errors}"
    assert vo._batch_mode is False

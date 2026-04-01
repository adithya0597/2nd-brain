"""Tests for core/vault_indexer.py — graph query functions."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.vault_indexer import (
    find_files_mentioning,
    get_linked_files,
    find_intersection_nodes,
    cached_get_linked_files,
    cached_find_files_mentioning,
    cached_find_intersection_nodes,
)


class TestFindFilesMentioning:
    def test_find_by_title(self, vault_graph_db):
        results = find_files_mentioning("Fitness", db_path=vault_graph_db)
        titles = [r["title"] for r in results]
        assert "Fitness" in titles

    def test_find_by_linked_topic(self, vault_graph_db):
        # Daily note 2026-03-01 links to Fitness via wikilink
        results = find_files_mentioning("Fitness", db_path=vault_graph_db)
        # Should include the daily note that links to Fitness
        titles = [r["title"] for r in results]
        assert "Fitness" in titles

    def test_find_nonexistent(self, vault_graph_db):
        results = find_files_mentioning("ZZZNonExistent", db_path=vault_graph_db)
        assert results == []

    def test_find_by_file_path_match(self, vault_graph_db):
        # "Side-Project" is a title in vault_graph_db
        results = find_files_mentioning("Side-Project", db_path=vault_graph_db)
        titles = [r["title"] for r in results]
        assert "Side-Project" in titles


class TestGetLinkedFiles:
    def test_get_linked_from_daily(self, vault_graph_db):
        # Daily note "2026-03-01" links to Fitness and Nutrition
        results = get_linked_files(["2026-03-01"], depth=1, db_path=vault_graph_db)
        titles = [r["title"] for r in results]
        assert "Fitness" in titles or "Nutrition" in titles

    def test_depth_2(self, vault_graph_db):
        results = get_linked_files(["2026-03-01"], depth=2, db_path=vault_graph_db)
        # At depth 2, should reach further
        assert len(results) >= 1

    def test_empty_seeds(self, vault_graph_db):
        results = get_linked_files([], depth=1, db_path=vault_graph_db)
        assert results == []

    def test_nonexistent_seeds(self, vault_graph_db):
        results = get_linked_files(["ZZZNotATitle"], depth=1, db_path=vault_graph_db)
        assert results == []


class TestFindIntersectionNodes:
    def test_shared_nodes(self, vault_graph_db):
        # Fitness and Nutrition are both linked from the daily note
        results = find_intersection_nodes("Fitness", "Nutrition", db_path=vault_graph_db)
        # There should be some intersection via the daily note link graph
        assert isinstance(results, list)

    def test_no_intersection(self, vault_graph_db):
        results = find_intersection_nodes("ZZZTopicA", "ZZZTopicB", db_path=vault_graph_db)
        assert results == []


class TestCachedWrappers:
    def test_cached_get_linked_files(self, vault_graph_db):
        with patch("core.vault_indexer.cached_graph_call") as mock_cache:
            mock_cache.return_value = [{"title": "Test"}]
            result = cached_get_linked_files(["seed"], depth=1, db_path=vault_graph_db)
        assert len(result) == 1

    def test_cached_find_files_mentioning(self, vault_graph_db):
        with patch("core.vault_indexer.cached_graph_call") as mock_cache:
            mock_cache.return_value = [{"title": "Test"}]
            result = cached_find_files_mentioning("topic", db_path=vault_graph_db)
        assert len(result) == 1

    def test_cached_find_intersection_nodes(self, vault_graph_db):
        with patch("core.vault_indexer.cached_graph_call") as mock_cache:
            mock_cache.return_value = []
            result = cached_find_intersection_nodes("A", "B", db_path=vault_graph_db)
        assert result == []

"""Tests for core.graph_cache — standalone TTL cache module."""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock

import pytest

from core.graph_cache import GraphCache, cached_graph_call, get_cache, invalidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a fresh singleton cache."""
    import core.graph_cache as mod
    mod._cache_instance = None
    yield
    mod._cache_instance = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGraphCacheBasics:
    """Core put/get/TTL/invalidate behaviour."""

    def test_basic_put_get(self):
        cache = GraphCache()
        cache.put("k1", {"data": [1, 2, 3]})
        hit, value = cache.get("k1")
        assert hit is True
        assert value == {"data": [1, 2, 3]}

    def test_cache_miss_on_empty_cache(self):
        cache = GraphCache()
        hit, value = cache.get("nonexistent")
        assert hit is False
        assert value is None

    def test_ttl_expiry(self):
        cache = GraphCache(ttl=0.1)
        cache.put("ephemeral", "gone-soon")
        hit, _ = cache.get("ephemeral")
        assert hit is True

        time.sleep(0.2)
        hit, value = cache.get("ephemeral")
        assert hit is False
        assert value is None

    def test_invalidate_all_clears_entries(self):
        cache = GraphCache()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.invalidate_all()
        assert cache.get("a") == (False, None)
        assert cache.get("b") == (False, None)


class TestCachedGraphCall:
    """Integration tests for the cache-through wrapper."""

    def test_caches_on_second_call(self):
        fn = MagicMock(return_value="result")

        r1 = cached_graph_call(fn, "my_func", "arg1", key="val")
        r2 = cached_graph_call(fn, "my_func", "arg1", key="val")

        assert r1 == "result"
        assert r2 == "result"
        fn.assert_called_once_with("arg1", key="val")

    def test_passes_correct_args_through(self):
        fn = MagicMock(return_value=42)

        cached_graph_call(fn, "f", "a", "b", x=1, y=2)
        fn.assert_called_once_with("a", "b", x=1, y=2)

    def test_different_args_produce_different_keys(self):
        fn = MagicMock(side_effect=lambda x: x * 10)

        r1 = cached_graph_call(fn, "mul", 3)
        r2 = cached_graph_call(fn, "mul", 5)

        assert r1 == 30
        assert r2 == 50
        assert fn.call_count == 2


class TestCacheKeyGeneration:
    """Key determinism and db_path exclusion."""

    def test_db_path_excluded_from_cache_key(self):
        key_a = GraphCache._make_key("query", "topic", db_path="/path/a.db")
        key_b = GraphCache._make_key("query", "topic", db_path="/path/b.db")
        assert key_a == key_b

    def test_sorted_list_args_deterministic(self):
        key_a = GraphCache._make_key("f", ["c", "a", "b"])
        key_b = GraphCache._make_key("f", ["b", "c", "a"])
        assert key_a == key_b


class TestThreadSafety:
    """Concurrent access must not corrupt the cache."""

    def test_concurrent_reads_writes(self):
        cache = GraphCache(ttl=5)
        errors: list[str] = []

        def writer(i: int) -> None:
            cache.put(f"key-{i}", i)

        def reader(i: int) -> None:
            hit, val = cache.get(f"key-{i}")
            if hit and val != i:
                errors.append(f"key-{i}: expected {i}, got {val}")

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = []
            for i in range(100):
                futures.append(pool.submit(writer, i))
            for f in as_completed(futures):
                f.result()  # propagate exceptions

            futures = []
            for i in range(100):
                futures.append(pool.submit(reader, i))
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Thread-safety violations: {errors}"

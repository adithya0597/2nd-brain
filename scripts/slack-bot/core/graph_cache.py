"""Thread-safe in-memory TTL cache for graph traversal query results.

Standalone module with no dependencies on the rest of the codebase.
Uses monotonic clock for TTL and SHA256 for deterministic cache keys.
"""

import hashlib
import json
import threading
import time
from typing import Any, Callable, Tuple

DEFAULT_TTL_SECONDS = 900  # 15 minutes


class GraphCache:
    """Thread-safe in-memory cache with per-entry TTL expiration."""

    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    @staticmethod
    def _make_key(func_name: str, *args: Any, **kwargs: Any) -> str:
        """Build a deterministic SHA256 cache key.

        - Excludes ``db_path`` from kwargs so the same logical query
          against different DB file paths shares a cache entry.
        - Sorts list arguments for order-independent matching.
        - Falls back to ``repr()`` for values that are not JSON-serialisable.
        """
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != "db_path"}

        def _normalize(obj: Any) -> Any:
            if isinstance(obj, list):
                try:
                    return sorted(obj)
                except TypeError:
                    # Elements are not comparable; preserve original order.
                    return obj
            return obj

        def _safe_serialize(obj: Any) -> Any:
            """Return a JSON-compatible representation, falling back to repr."""
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            if isinstance(obj, (list, tuple)):
                return [_safe_serialize(i) for i in obj]
            if isinstance(obj, dict):
                return {str(k): _safe_serialize(v) for k, v in obj.items()}
            # Unhashable / non-serialisable → deterministic string fallback
            return repr(obj)

        normalized_args = [_normalize(a) for a in args]
        normalized_kwargs = {k: _normalize(v) for k, v in sorted(filtered_kwargs.items())}

        payload = _safe_serialize({
            "func": func_name,
            "args": normalized_args,
            "kwargs": normalized_kwargs,
        })

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Tuple[bool, Any]:
        """Return ``(hit, value)``.  Expired entries are evicted on read."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False, None
            ts, value = entry
            if (time.monotonic() - ts) > self._ttl:
                del self._store[key]
                return False, None
            return True, value

    def put(self, key: str, value: Any) -> None:
        """Store *value* under *key* with the current monotonic timestamp."""
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def invalidate_all(self) -> None:
        """Drop every entry in the cache."""
        with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# Module-level singleton API
# ---------------------------------------------------------------------------

_cache_instance: GraphCache | None = None
_instance_lock = threading.Lock()


def get_cache(ttl: float = DEFAULT_TTL_SECONDS) -> GraphCache:
    """Return (or create) the module-level singleton ``GraphCache``."""
    global _cache_instance
    if _cache_instance is None:
        with _instance_lock:
            # Double-checked locking
            if _cache_instance is None:
                _cache_instance = GraphCache(ttl=ttl)
    return _cache_instance


def cached_graph_call(func: Callable, func_name: str, *args: Any, **kwargs: Any) -> Any:
    """Cache-through wrapper: return cached result or call *func* and cache it.

    Parameters
    ----------
    func:
        The callable to invoke on a cache miss.
    func_name:
        A stable string identifier used in the cache key (avoids relying on
        ``func.__name__`` which can differ across reloads).
    *args, **kwargs:
        Forwarded to both the key builder and to *func* on a miss.
    """
    cache = get_cache()
    key = GraphCache._make_key(func_name, *args, **kwargs)
    hit, value = cache.get(key)
    if hit:
        return value
    result = func(*args, **kwargs)
    cache.put(key, result)
    return result


def invalidate() -> None:
    """Clear the singleton cache (e.g. after a vault reindex)."""
    global _cache_instance
    if _cache_instance is not None:
        _cache_instance.invalidate_all()

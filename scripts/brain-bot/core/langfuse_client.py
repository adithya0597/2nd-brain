"""Langfuse observability client -- singleton with graceful degradation.

Fully optional: returns None if LANGFUSE_ENABLED is false, keys are missing,
or the langfuse package is not installed. All callers should guard with
``if lf is not None:`` before calling any Langfuse method.

This module has NO project imports (standalone) to avoid circular dependencies.
"""
import logging
import os

logger = logging.getLogger(__name__)

_client = None
_initialized = False


def get_langfuse():
    """Return shared Langfuse client, or None if disabled/unconfigured.

    Checks (in order):
    1. LANGFUSE_ENABLED env var (default "false")
    2. LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be non-empty
    3. ``langfuse`` package must be importable

    Returns the same singleton on subsequent calls.
    """
    global _client, _initialized
    if _initialized:
        return _client

    _initialized = True

    enabled = os.environ.get("LANGFUSE_ENABLED", "false").lower() in ("true", "1", "yes")
    if not enabled:
        logger.debug("Langfuse disabled (LANGFUSE_ENABLED != true)")
        _client = None
        return _client

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        logger.debug("Langfuse disabled (missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY)")
        _client = None
        return _client

    try:
        from langfuse import Langfuse

        base_url = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=base_url,
        )
        logger.info("Langfuse client initialized (host=%s)", base_url)
        return _client
    except ImportError:
        logger.debug("Langfuse package not installed -- observability disabled")
        _client = None
        return _client
    except Exception:
        logger.debug("Langfuse initialization failed", exc_info=True)
        _client = None
        return _client


def reset_client():
    """Reset singleton for testing."""
    global _client, _initialized
    _client = None
    _initialized = False


def flush():
    """Flush pending Langfuse events. Call on shutdown."""
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            logger.debug("Langfuse flush failed", exc_info=True)

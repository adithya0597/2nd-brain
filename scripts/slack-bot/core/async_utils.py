"""Centralized async-to-sync bridge for background threads."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Shared executor for all background work (replaces daemon threads)
executor = ThreadPoolExecutor(max_workers=8)


def run_async(coro):
    """Run an async coroutine from a sync context (background thread).

    Creates a new event loop, runs the coroutine, and closes the loop.
    This replaces the duplicated pattern across all handler modules.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def shutdown():
    """Shutdown the thread pool executor."""
    executor.shutdown(wait=True, cancel_futures=False)

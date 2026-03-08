"""Async utilities for the Telegram bot.

PTB v21 is fully async, so the sync-to-async bridge (run_async) is no longer
needed. This module provides only CPU-bound offloading via a thread pool.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Shared executor for CPU-bound work (embedding computation, file parsing, etc.)
executor = ThreadPoolExecutor(max_workers=8)


async def run_in_executor(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """Run a sync/CPU-bound function in the thread pool executor.

    Use this for operations like sentence-transformer inference, heavy file
    parsing, or any blocking call that shouldn't stall the async event loop.
    """
    loop = asyncio.get_running_loop()
    if kwargs:
        func = partial(func, **kwargs)
    return await loop.run_in_executor(executor, func, *args)


def shutdown():
    """Shutdown the thread pool executor."""
    executor.shutdown(wait=True, cancel_futures=False)

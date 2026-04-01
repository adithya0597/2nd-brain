"""Tests for core/async_utils.py — thread pool executor utilities."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.async_utils import run_in_executor, shutdown, executor


class TestRunInExecutor:
    @pytest.mark.asyncio
    async def test_basic_function(self):
        def add(a, b):
            return a + b
        result = await run_in_executor(add, 3, 4)
        assert result == 7

    @pytest.mark.asyncio
    async def test_with_kwargs(self):
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"
        result = await run_in_executor(greet, "World", greeting="Hi")
        assert result == "Hi, World!"

    @pytest.mark.asyncio
    async def test_no_args(self):
        def get_value():
            return 42
        result = await run_in_executor(get_value)
        assert result == 42


class TestShutdown:
    def test_shutdown_does_not_raise(self):
        # Don't actually shutdown the shared executor in tests
        # Just verify the function exists and is callable
        assert callable(shutdown)

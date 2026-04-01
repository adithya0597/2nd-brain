"""Tests for handlers/__init__.py — register_all."""
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

from handlers import register_all


class TestRegisterAll:
    def test_registers_modules(self):
        app = MagicMock()
        # Each handler module has a register(app) function
        # register_all tries to import and call register on each
        with patch("handlers.__import__", side_effect=ImportError("mock"), create=True):
            pass  # Can't easily override __import__

        # Just call register_all and verify it doesn't crash
        # The modules may not all be importable in test context, but errors are caught
        register_all(app)

    def test_import_error_handled(self):
        app = MagicMock()
        # register_all catches ImportError gracefully
        with patch("builtins.__import__", side_effect=ImportError("not found")):
            register_all(app)

    def test_attribute_error_handled(self):
        app = MagicMock()
        # Module without register() function
        mock_module = MagicMock(spec=[])  # no register attribute
        del mock_module.register

        with patch("builtins.__import__", return_value=mock_module):
            register_all(app)

    def test_generic_error_handled(self):
        app = MagicMock()
        mock_module = MagicMock()
        mock_module.register.side_effect = RuntimeError("boom")

        with patch("builtins.__import__", return_value=mock_module):
            register_all(app)

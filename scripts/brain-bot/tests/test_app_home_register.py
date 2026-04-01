"""Tests for handlers/app_home.py — placeholder module."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from handlers.app_home import register


class TestAppHomeRegister:
    def test_noop(self):
        app = MagicMock()
        register(app)
        # Should not register any handlers
        app.add_handler.assert_not_called()

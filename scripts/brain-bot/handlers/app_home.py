"""Telegram App Home / settings view handler.

The Slack App Home tab has no direct Telegram equivalent.
This module is a placeholder for future /settings or inline-menu features.
"""

import logging

logger = logging.getLogger(__name__)


def register(application):
    """No-op: App Home not applicable to Telegram."""
    logger.debug("app_home: no Telegram equivalent, skipping registration")

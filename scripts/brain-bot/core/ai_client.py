"""Centralized async Anthropic client singleton.

PTB v21 is fully async — using a sync Anthropic client would block the event
loop for 10-60s per AI call. AsyncAnthropic is required.
"""
import sys

import anthropic

_client = None
_initialized = False


def get_ai_client():
    """Return shared AsyncAnthropic client, or None if no API key configured."""
    global _client, _initialized
    if _initialized:
        return _client
    config = sys.modules.get("config")
    api_key = getattr(config, "ANTHROPIC_API_KEY", "") if config else ""
    if api_key:
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    else:
        _client = None
    _initialized = True
    return _client


def get_ai_model():
    """Return the configured model name."""
    config = sys.modules.get("config")
    return getattr(config, "ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


def reset_client():
    """Reset singleton for testing."""
    global _client, _initialized
    _client = None
    _initialized = False

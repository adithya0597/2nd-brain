"""Centralized Anthropic client singleton."""
import sys

import anthropic

_client = None
_initialized = False


def get_ai_client():
    """Return shared Anthropic client, or None if no API key configured."""
    global _client, _initialized
    if _initialized:
        return _client
    config = sys.modules.get("config")
    api_key = getattr(config, "ANTHROPIC_API_KEY", "") if config else ""
    if api_key:
        _client = anthropic.Anthropic(api_key=api_key)
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

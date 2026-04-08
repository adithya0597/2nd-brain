"""Centralized async AI client singleton — model-agnostic.

Supports multiple backends via AI_PROVIDER env var:
  - "gemini" (default): Google Gemini via google-genai SDK
  - "anthropic": Anthropic Claude via anthropic SDK

All callers use the same interface:
    ai = get_ai_client()
    response = await ai.messages.create(
        model=get_ai_model(),
        max_tokens=4096,
        system=[{"type": "text", "text": "..."}],
        messages=[{"role": "user", "content": "..."}],
    )
    text = response.content[0].text
    tokens = response.usage.input_tokens

To switch providers, change AI_PROVIDER, AI_API_KEY, and AI_MODEL in .env.
"""
import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

_client = None
_initialized = False
_ai_semaphore = asyncio.Semaphore(1)


# ---------------------------------------------------------------------------
# Shared response types (provider-agnostic)
# ---------------------------------------------------------------------------

class _ContentBlock:
    """Mimics anthropic.types.ContentBlock."""
    def __init__(self, text: str):
        self.text = text


class _Usage:
    """Mimics anthropic.types.Usage."""
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _Response:
    """Mimics anthropic.types.Message."""
    def __init__(self, text: str, model: str = "", input_tokens: int = 0, output_tokens: int = 0):
        self.content = [_ContentBlock(text)]
        self.usage = _Usage(input_tokens, output_tokens)
        self.model = model
        self.id = "response"
        self.type = "message"
        self.role = "assistant"
        self.stop_reason = "end_turn"


# ---------------------------------------------------------------------------
# Gemini backend
# ---------------------------------------------------------------------------

class _GeminiMessages:
    """Translates Anthropic-style messages.create() to Gemini API."""
    def __init__(self, genai_client, default_model: str):
        self._client = genai_client
        self._model = default_model

    async def create(self, *, model: str = None, max_tokens: int = 4096,
                     system=None, messages=None, **kwargs) -> _Response:
        import asyncio
        from google.genai import types

        use_model = model or self._model

        # Build system instruction
        system_text = ""
        if system:
            if isinstance(system, str):
                system_text = system
            elif isinstance(system, list):
                parts = []
                for item in system:
                    if isinstance(item, dict):
                        parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        parts.append(item)
                system_text = "\n\n".join(p for p in parts if p)

        # Build conversation contents
        contents = []
        if messages:
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = "\n".join(text_parts)
                gemini_role = "model" if role == "assistant" else "user"
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        config = types.GenerateContentConfig(
            system_instruction=system_text if system_text else None,
            max_output_tokens=max_tokens,
        )

        def _sync_call():
            return self._client.models.generate_content(
                model=use_model, contents=contents, config=config,
            )

        loop = asyncio.get_event_loop()

        async with _ai_semaphore:
            response = None
            for attempt in range(3):
                try:
                    response = await loop.run_in_executor(None, _sync_call)
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    is_rate_limit = "429" in err_str or "rate" in err_str
                    is_quota = "quota" in err_str or "resource_exhausted" in err_str
                    if is_rate_limit and not is_quota and attempt < 2:
                        wait = 2 ** (attempt + 1)
                        logger.warning("Gemini rate limited (attempt %d/3), retrying in %ds", attempt + 1, wait)
                        await asyncio.sleep(wait)
                        continue
                    raise

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        return _Response(
            text=response.text or "",
            model=use_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class _GeminiClient:
    """Drop-in for anthropic.AsyncAnthropic with .messages.create()."""
    def __init__(self, genai_client, default_model: str):
        self.messages = _GeminiMessages(genai_client, default_model)


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

class _AnthropicClient:
    """Thin wrapper — just returns the real AsyncAnthropic client."""
    def __init__(self, api_key: str):
        import anthropic
        self._inner = anthropic.AsyncAnthropic(api_key=api_key)
        self.messages = self._inner.messages


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _detect_provider():
    """Detect which AI provider to use from config."""
    config = sys.modules.get("config")
    # Explicit provider override
    provider = getattr(config, "AI_PROVIDER", "") if config else ""
    if provider:
        return provider.lower()
    # Auto-detect: if GEMINI_API_KEY is set, use gemini; if ANTHROPIC_API_KEY, use anthropic
    gemini_key = getattr(config, "GEMINI_API_KEY", "") if config else ""
    anthropic_key = getattr(config, "ANTHROPIC_API_KEY", "") if config else ""
    if gemini_key:
        return "gemini"
    if anthropic_key:
        return "anthropic"
    return None


def get_ai_client():
    """Return shared AI client, or None if no API key configured.

    Auto-detects provider from env vars. Override with AI_PROVIDER=gemini|anthropic.
    """
    global _client, _initialized
    if _initialized:
        return _client

    config = sys.modules.get("config")
    provider = _detect_provider()

    if provider == "gemini":
        api_key = getattr(config, "GEMINI_API_KEY", "")
        model = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")
        try:
            from google import genai
            genai_client = genai.Client(api_key=api_key)
            _client = _GeminiClient(genai_client, model)
            logger.info("AI client initialized (Gemini: %s)", model)
        except Exception as e:
            logger.error("Failed to initialize Gemini client: %s", e)
            _client = None

    elif provider == "anthropic":
        api_key = getattr(config, "ANTHROPIC_API_KEY", "")
        try:
            _client = _AnthropicClient(api_key)
            logger.info("AI client initialized (Anthropic: %s)",
                        getattr(config, "ANTHROPIC_MODEL", "claude-sonnet"))
        except Exception as e:
            logger.error("Failed to initialize Anthropic client: %s", e)
            _client = None

    else:
        logger.warning("No AI provider configured. Set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env")
        _client = None

    _initialized = True
    return _client


def get_ai_model():
    """Return the configured model name for the active provider."""
    config = sys.modules.get("config")
    provider = _detect_provider()
    if provider == "gemini":
        return getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")
    elif provider == "anthropic":
        return getattr(config, "ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    return "unknown"


_anthropic_client = None
_anthropic_initialized = False


def get_anthropic_client():
    """Return a dedicated Anthropic client for high-volume/cheap calls (e.g. distiller).

    Bypasses the AI_PROVIDER auto-detect so callers always get Anthropic/Haiku
    regardless of whether the main provider is Gemini.
    Returns None if ANTHROPIC_API_KEY is not set.
    """
    global _anthropic_client, _anthropic_initialized
    if _anthropic_initialized:
        return _anthropic_client

    config = sys.modules.get("config")
    api_key = getattr(config, "ANTHROPIC_API_KEY", "") if config else ""
    if api_key:
        try:
            _anthropic_client = _AnthropicClient(api_key)
            logger.info("Dedicated Anthropic client initialized for distiller")
        except Exception as e:
            logger.error("Failed to initialize Anthropic client: %s", e)
            _anthropic_client = None
    else:
        _anthropic_client = None

    _anthropic_initialized = True
    return _anthropic_client


def reset_client():
    """Reset singleton for testing."""
    global _client, _initialized, _anthropic_client, _anthropic_initialized
    _client = None
    _initialized = False
    _anthropic_client = None
    _anthropic_initialized = False


async def get_daily_token_usage() -> int:
    """Sum tokens used today from api_token_logs."""
    try:
        from core.db_ops import query
        rows = await query(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) as total "
            "FROM api_token_logs WHERE created_at >= date('now')"
        )
        return rows[0]["total"] if rows else 0
    except Exception:
        logger.debug("Could not query daily token usage", exc_info=True)
        return 0

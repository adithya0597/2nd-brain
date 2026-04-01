"""Structured knowledge extraction from articles.

Phase 2 of the knowledge pipeline: takes raw article text,
calls Gemini with JSON mode to extract claims, frameworks,
action items, and key concepts, then creates concept stubs
in the vault.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Minimum content length to attempt extraction
_MIN_CONTENT_LENGTH = 200
# Maximum content length sent to the LLM
_MAX_CONTENT_LENGTH = 30_000

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured knowledge from articles. Return JSON:\n"
    '{"summary": "2-3 sentences", '
    '"claims": [{"text": "...", "confidence": "high|medium|low", "source_context": "..."}], '
    '"frameworks": [{"name": "...", "description": "..."}], '
    '"action_items": [{"description": "...", "context": "..."}], '
    '"key_concepts": ["Concept 1", "Concept 2"]}\n'
    "Rules: 8-18 claims by length, 2-5 frameworks ([] if none), "
    "3-8 action items, 5-10 key_concepts as Title Case. "
    "Do NOT invent claims."
)

# Regex to strip ```json ... ``` fences that Gemini sometimes wraps around JSON
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", re.DOTALL)


@dataclass
class ExtractedClaim:
    text: str
    confidence: str  # "high", "medium", "low"
    source_context: str


@dataclass
class ExtractedFramework:
    name: str
    description: str


@dataclass
class ExtractedActionItem:
    description: str
    context: str


@dataclass
class ExtractionResult:
    claims: list[ExtractedClaim] = field(default_factory=list)
    frameworks: list[ExtractedFramework] = field(default_factory=list)
    action_items: list[ExtractedActionItem] = field(default_factory=list)
    key_concepts: list[str] = field(default_factory=list)
    summary: str = ""
    raw_json: dict = field(default_factory=dict)


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from a JSON response."""
    text = text.strip()
    m = _CODE_FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text


def _parse_extraction_json(raw: dict) -> ExtractionResult:
    """Parse a raw JSON dict into an ExtractionResult."""
    claims = []
    for c in raw.get("claims", []):
        if isinstance(c, dict) and "text" in c:
            claims.append(ExtractedClaim(
                text=c["text"],
                confidence=c.get("confidence", "medium"),
                source_context=c.get("source_context", ""),
            ))

    frameworks = []
    for f in raw.get("frameworks", []):
        if isinstance(f, dict) and "name" in f:
            frameworks.append(ExtractedFramework(
                name=f["name"],
                description=f.get("description", ""),
            ))

    action_items = []
    for a in raw.get("action_items", []):
        if isinstance(a, dict) and "description" in a:
            action_items.append(ExtractedActionItem(
                description=a["description"],
                context=a.get("context", ""),
            ))

    key_concepts = [
        k for k in raw.get("key_concepts", [])
        if isinstance(k, str)
    ]

    return ExtractionResult(
        claims=claims,
        frameworks=frameworks,
        action_items=action_items,
        key_concepts=key_concepts,
        summary=raw.get("summary", ""),
        raw_json=raw,
    )


async def extract_knowledge(
    article_text: str,
    title: str = "",
    url: str = "",
) -> ExtractionResult | None:
    """Extract structured knowledge from article text via Gemini JSON mode.

    Args:
        article_text: The plain-text content of the article.
        title: Article title (included in the prompt for context).
        url: Article URL (included in the prompt for context).

    Returns:
        ExtractionResult on success, None on failure or if content is too short.
    """
    if len(article_text) < _MIN_CONTENT_LENGTH:
        logger.info("Content too short for extraction (%d chars)", len(article_text))
        return None

    # Truncate long content
    truncated = article_text[:_MAX_CONTENT_LENGTH]

    # Build user message
    user_parts = []
    if title:
        user_parts.append(f"Title: {title}")
    if url:
        user_parts.append(f"URL: {url}")
    user_parts.append(f"Article:\n{truncated}")
    user_message = "\n\n".join(user_parts)

    try:
        from core.ai_client import generate_text, get_ai_model

        text, response = await generate_text(
            system=_EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=4096,
            response_mime_type="application/json",
            trace_metadata={"caller": "content_extractor"},
        )

        # Log token usage
        try:
            from core.token_logger import log_token_usage
            log_token_usage(response, caller="content_extractor", model=get_ai_model())
        except Exception:
            logger.debug("Token logging failed for content_extractor", exc_info=True)

        # Strip code fences (Gemini sometimes wraps JSON in ```json...```)
        cleaned = _strip_code_fences(text)

        # Parse JSON
        raw = json.loads(cleaned)
        if not isinstance(raw, dict):
            logger.warning("Extraction returned non-dict JSON: %s", type(raw))
            return None

        return _parse_extraction_json(raw)

    except json.JSONDecodeError:
        logger.warning("Failed to parse extraction JSON", exc_info=True)
        return None
    except RuntimeError:
        logger.warning("Gemini API not configured for extraction")
        return None
    except Exception:
        logger.exception("Knowledge extraction failed")
        return None


def _ensure_concept_stubs(
    key_concepts: list[str],
    source_url: str,
    source_title: str,
    icor_elements: list[str] | None = None,
) -> list[Path]:
    """Create concept stub files for any concepts that don't already exist.

    Args:
        key_concepts: List of concept names to ensure.
        source_url: URL of the source article.
        source_title: Title of the source article.
        icor_elements: Optional ICOR elements to tag the concepts with.

    Returns:
        List of paths to newly created concept files.
    """
    import config
    from core.vault_ops import _sanitize_filename, create_concept_file

    created = []
    for concept in key_concepts:
        sanitized = _sanitize_filename(concept)
        path = config.VAULT_PATH / "Concepts" / f"{sanitized}.md"
        if path.exists():
            logger.debug("Concept stub already exists: %s", path)
            continue

        summary = f"Extracted from [{source_title}]({source_url})"
        new_path = create_concept_file(
            name=concept,
            summary=summary,
            icor_elements=icor_elements,
            status="seedling",
        )
        created.append(new_path)
        logger.info("Created concept stub: %s", new_path)

    return created

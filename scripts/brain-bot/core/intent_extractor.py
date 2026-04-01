"""Intent and entity extraction from captures via LLM."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from difflib import get_close_matches

from core.ai_client import get_ai_client, get_ai_model

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Structured extraction from a capture message."""

    intent: str = "reflection"  # task, idea, reflection, update, link, question
    title: str = ""
    people: list[str] = field(default_factory=list)
    project: str | None = None
    due_date: str | None = None  # ISO format YYYY-MM-DD
    priority: str | None = None  # high, medium, low
    confidence: float = 0.0
    raw_response: str = ""


def _build_extraction_prompt(
    text: str, project_names: list[str], people_names: list[str]
) -> str:
    """Build the LLM prompt for intent/entity extraction."""
    today = date.today().isoformat()
    projects_str = ", ".join(project_names[:20]) if project_names else "none known"
    people_str = ", ".join(people_names[:20]) if people_names else "none known"

    return (
        f"Extract structured information from this capture message. Today is {today}.\n\n"
        f"KNOWN PROJECTS: {projects_str}\n"
        f"KNOWN PEOPLE: {people_str}\n\n"
        f'MESSAGE: "{text}"\n\n'
        "Return a JSON object with these fields:\n"
        '- "intent": one of "task", "idea", "reflection", "update", "link", "question"\n'
        '- "title": a clean, concise title for this item (imperative form for tasks, '
        'e.g. "Call Sarah about pitch deck")\n'
        '- "people": list of person names mentioned (empty list if none)\n'
        '- "project": the project this relates to from the known projects list, or null if unclear\n'
        f'- "due_date": ISO date (YYYY-MM-DD) if a deadline is mentioned (resolve "tomorrow", '
        f'"Friday", "next week", "in 2 days" etc relative to today {today}), or null\n'
        '- "priority": "high", "medium", or "low" if inferable from urgency words, or null\n'
        "- \"confidence\": 0.0 to 1.0 how confident you are in this extraction\n\n"
        "Return ONLY the JSON object, no other text."
    )


def _parse_extraction_response(response_text: str) -> dict:
    """Parse LLM response into extraction dict."""
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse extraction response: %s", text[:200])
        return {}


def _fuzzy_match_project(
    extracted_project: str | None, known_projects: list[str]
) -> str | None:
    """Fuzzy-match extracted project name against known projects."""
    if not extracted_project or not known_projects:
        return None
    lower_projects = [p.lower() for p in known_projects]
    matches = get_close_matches(
        extracted_project.lower(), lower_projects, n=1, cutoff=0.4
    )
    if matches:
        idx = lower_projects.index(matches[0])
        return known_projects[idx]
    return None


def _load_registry() -> dict:
    """Load notion-registry.json data."""
    import config

    registry_path = config.NOTION_REGISTRY_PATH
    if registry_path.exists():
        return json.loads(registry_path.read_text(encoding="utf-8"))
    return {}


async def extract_intent(text: str, registry_data: dict) -> ExtractionResult:
    """Extract intent, entities, and actions from a capture message.

    Args:
        text: The raw capture message text
        registry_data: The notion-registry.json data dict

    Returns:
        ExtractionResult with extracted fields
    """
    project_names = list(registry_data.get("projects", {}).keys())
    people_names = list(registry_data.get("people", {}).keys()) if "people" in registry_data else []

    prompt = _build_extraction_prompt(text, project_names, people_names)

    try:
        client = get_ai_client()
        if client is None:
            logger.warning("No AI client available for intent extraction")
            return ExtractionResult(intent="reflection", title=text[:80], confidence=0.0)

        model = get_ai_model()

        response = await client.messages.create(
            model=model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": "You are a precise JSON extraction engine. Return only valid JSON.",
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        parsed = _parse_extraction_response(raw)

        if not parsed:
            return ExtractionResult(raw_response=raw)

        # Fuzzy-match project
        matched_project = _fuzzy_match_project(parsed.get("project"), project_names)

        return ExtractionResult(
            intent=parsed.get("intent", "reflection"),
            title=parsed.get("title", text[:80]),
            people=parsed.get("people", []),
            project=matched_project,
            due_date=parsed.get("due_date"),
            priority=parsed.get("priority"),
            confidence=parsed.get("confidence", 0.5),
            raw_response=raw,
        )

    except Exception as e:
        logger.error("Intent extraction failed: %s", e)
        return ExtractionResult(
            intent="reflection",
            title=text[:80],
            confidence=0.0,
        )

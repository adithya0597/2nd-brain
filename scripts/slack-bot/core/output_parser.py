"""Parse structured output from Claude AI command responses."""
import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ParsedConcept:
    title: str
    summary: str
    icor_elements: list[str] = field(default_factory=list)
    status: str = "seedling"
    source_dates: list[str] = field(default_factory=list)
    first_mentioned: str = ""
    last_mentioned: str = ""
    mention_count: int = 1


def parse_graduate_output(result_text: str) -> list[ParsedConcept]:
    """Extract concept data from Claude's graduate command response.

    Looks for a ```json block containing a "concepts" array.
    Falls back to parsing markdown headers if no JSON found.
    """
    concepts = []

    # Try JSON block first
    json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            for c in data.get("concepts", []):
                concepts.append(ParsedConcept(
                    title=c.get("title", ""),
                    summary=c.get("summary", ""),
                    icor_elements=c.get("icor_elements", []),
                    status=c.get("status", "seedling"),
                    source_dates=c.get("source_dates", []),
                    first_mentioned=c.get("first_mentioned", ""),
                    last_mentioned=c.get("last_mentioned", ""),
                    mention_count=c.get("mention_count", 1),
                ))
            if concepts:
                return concepts
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse graduate JSON block: %s", e)

    # Fallback: parse markdown "### Concept N: Title" blocks
    concept_blocks = re.split(r'###\s+Concept\s+\d+:\s+', result_text)
    for block in concept_blocks[1:]:  # Skip text before first concept
        lines = block.strip().split('\n')
        if not lines:
            continue
        title = lines[0].strip().rstrip('#').strip()
        if not title:
            continue

        summary = ""
        icor_elements = []
        sources = []

        for line in lines[1:]:
            line = line.strip()
            if line.startswith("- **Summary:**"):
                summary = line.replace("- **Summary:**", "").strip()
            elif line.startswith("- **ICOR Elements:**"):
                raw = line.replace("- **ICOR Elements:**", "").strip()
                icor_elements = [e.strip() for e in raw.split(",") if e.strip()]
            elif line.startswith("- **Sources:**"):
                raw = line.replace("- **Sources:**", "").strip()
                sources = [s.strip() for s in raw.split(",") if s.strip()]

        if title:
            concepts.append(ParsedConcept(
                title=title,
                summary=summary or f"Concept graduated from daily notes",
                icor_elements=icor_elements,
                source_dates=sources,
                first_mentioned=sources[0] if sources else "",
                last_mentioned=sources[-1] if sources else "",
                mention_count=len(sources) or 1,
            ))

    return concepts

"""Quality gate for validating LLM-generated vault content."""
import logging
import re
from pathlib import Path

import yaml

import config

logger = logging.getLogger(__name__)


def validate_vault_write(content: str, file_path: Path) -> list[str]:
    """Validate content before writing to vault.

    Returns list of issues found. Empty list means content is safe to write.
    Used by the distiller (Phase B) before writing to vault, not for
    existing trusted paths (captures, reports).
    """
    issues = []

    # Check for broken wikilinks
    for link in re.findall(r"\[\[([^\]]+)\]\]", content):
        # Strip display text (e.g. [[path|display]])
        target_name = link.split("|")[0].strip()
        target = config.VAULT_PATH / f"{target_name}.md"
        dim_target = config.VAULT_PATH / "Dimensions" / f"{target_name}.md"
        concept_target = config.VAULT_PATH / "Concepts" / f"{target_name}.md"
        if not target.exists() and not dim_target.exists() and not concept_target.exists():
            issues.append(f"Broken wikilink: [[{target_name}]]")

    # Validate YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                yaml.safe_load(parts[1])
            except Exception as e:
                issues.append(f"Invalid YAML frontmatter: {e}")

    # Flag suspiciously long content (hallucination signal)
    word_count = len(content.split())
    if word_count > 2000:
        issues.append(f"Suspiciously long content ({word_count} words)")

    if issues:
        logger.warning("Quality gate issues for %s: %s", file_path, issues)

    return issues

"""Journal indexer: parse daily notes into journal_entries table."""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import yaml

import config
from core.db_connection import get_connection

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)

# Heuristic patterns for mood/energy extraction from content
MOOD_PATTERNS = {
    "great": re.compile(r"\b(amazing|wonderful|fantastic|excellent|great day|thrilled)\b", re.I),
    "good": re.compile(r"\b(good|happy|positive|productive|satisf|enjoy)\b", re.I),
    "okay": re.compile(r"\b(okay|alright|fine|neutral|so-so|meh)\b", re.I),
    "low": re.compile(r"\b(tired|frustrated|stressed|anxious|overwhelmed|difficult)\b", re.I),
    "bad": re.compile(r"\b(terrible|awful|horrible|miserable|depressed|angry)\b", re.I),
}

ENERGY_PATTERNS = {
    "high": re.compile(r"\b(energized|motivated|pumped|focused|alert|high energy)\b", re.I),
    "medium": re.compile(r"\b(moderate|steady|normal|balanced|fine)\b", re.I),
    "low": re.compile(r"\b(exhausted|drained|tired|fatigued|low energy|sluggish)\b", re.I),
}

# ICOR dimension names for detecting mentions
ICOR_DIMENSIONS = list(config.DIMENSION_TOPICS.keys())

# Keywords that map to ICOR dimensions (broader than routing keywords)
ICOR_KEYWORDS = {
    "Health & Vitality": ["health", "fitness", "workout", "diet", "sleep", "exercise", "gym", "meditation", "yoga", "running", "nutrition", "mental health", "doctor", "therapy"],
    "Wealth & Finance": ["money", "finance", "invest", "budget", "savings", "income", "expense", "crypto", "stocks", "salary", "debt", "business", "revenue", "portfolio"],
    "Relationships": ["friend", "family", "relationship", "partner", "social", "community", "mentor", "colleague", "dating", "hangout", "catch up", "dinner with"],
    "Mind & Growth": ["learn", "read", "book", "course", "study", "skill", "knowledge", "research", "education", "creative", "writing", "art", "music"],
    "Purpose & Impact": ["career", "mission", "purpose", "impact", "volunteer", "leadership", "legacy", "values", "give back", "content creation", "brand"],
    "Systems & Environment": ["system", "automate", "tool", "setup", "organize", "clean", "home", "workspace", "routine", "habit", "process", "workflow"],
}


def _extract_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from content."""
    return FRONTMATTER_RE.sub("", content).strip()


def _detect_mood(content: str, frontmatter: dict) -> str:
    """Detect mood from frontmatter or content heuristics."""
    if fm_mood := frontmatter.get("mood"):
        return str(fm_mood).lower()

    scores = {}
    for mood, pattern in MOOD_PATTERNS.items():
        matches = pattern.findall(content)
        if matches:
            scores[mood] = len(matches)

    if scores:
        return max(scores, key=scores.get)
    return ""


def _detect_energy(content: str, frontmatter: dict) -> str:
    """Detect energy level from frontmatter or content heuristics."""
    if fm_energy := frontmatter.get("energy"):
        return str(fm_energy).lower()

    scores = {}
    for energy, pattern in ENERGY_PATTERNS.items():
        matches = pattern.findall(content)
        if matches:
            scores[energy] = len(matches)

    if scores:
        return max(scores, key=scores.get)
    return ""


def _detect_icor_elements(content: str, frontmatter: dict) -> list[str]:
    """Detect ICOR dimension mentions from content."""
    # Check frontmatter first
    if fm_elements := frontmatter.get("icor_elements"):
        if isinstance(fm_elements, list):
            return fm_elements

    found = set()
    content_lower = content.lower()

    for dim, keywords in ICOR_KEYWORDS.items():
        for kw in keywords:
            if kw in content_lower:
                found.add(dim)
                break

    return sorted(found)


def _generate_summary(content: str, max_length: int = 200) -> str:
    """Generate a brief summary from the body content."""
    body = _strip_frontmatter(content)
    # Take first non-empty, non-heading paragraph
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("---"):
            if len(line) > max_length:
                return line[:max_length] + "..."
            return line
    return ""


def parse_daily_note(file_path: Path) -> dict | None:
    """Parse a single daily note file into a journal entry dict.

    Returns None if the file cannot be parsed or has no meaningful content.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Could not read daily note: %s", file_path)
        return None

    # Extract date from filename (YYYY-MM-DD.md)
    date_str = file_path.stem
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning("Invalid date in filename: %s", file_path)
        return None

    body = _strip_frontmatter(content)
    if len(body) < 20:
        # Too short to be meaningful
        return None

    fm = _extract_frontmatter(content)

    return {
        "date": date_str,
        "content": body,
        "mood": _detect_mood(body, fm),
        "energy": _detect_energy(body, fm),
        "icor_elements": _detect_icor_elements(body, fm),
        "summary": fm.get("summary") or _generate_summary(content),
        "sentiment_score": 0.0,  # Placeholder — AI can enrich later
    }


def scan_daily_notes(vault_path: Path = None) -> list[dict]:
    """Scan all daily notes and parse them into journal entry dicts."""
    vault_path = vault_path or config.VAULT_PATH
    notes_dir = vault_path / "Daily Notes"
    if not notes_dir.exists():
        logger.info("Daily Notes directory not found at %s", notes_dir)
        return []

    entries = []
    for md_file in sorted(notes_dir.glob("*.md")):
        entry = parse_daily_note(md_file)
        if entry:
            entries.append(entry)

    return entries


def index_to_db(entries: list[dict], db_path: Path = None):
    """Write journal entries to SQLite (upsert by date)."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        for entry in entries:
            # Upsert: insert or update existing entry for the same date
            cursor.execute(
                "INSERT INTO journal_entries (date, content, mood, energy, icor_elements, summary, sentiment_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(date) DO UPDATE SET "
                "content = excluded.content, mood = excluded.mood, energy = excluded.energy, "
                "icor_elements = excluded.icor_elements, summary = excluded.summary, "
                "sentiment_score = excluded.sentiment_score",
                (
                    entry["date"],
                    entry["content"],
                    entry["mood"],
                    entry["energy"],
                    json.dumps(entry["icor_elements"]),
                    entry["summary"],
                    entry["sentiment_score"],
                ),
            )

        conn.commit()
    logger.info("Indexed %d journal entries to %s", len(entries), db_path or config.DB_PATH)


def run_full_index(vault_path: Path = None, db_path: Path = None) -> int:
    """Scan daily notes and write to DB. Returns number of entries indexed."""
    entries = scan_daily_notes(vault_path)
    if entries:
        index_to_db(entries, db_path)
    return len(entries)

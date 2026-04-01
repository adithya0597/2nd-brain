"""Configuration for Second Brain Telegram Bot."""
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OWNER_TELEGRAM_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "0"))

# AI Provider — auto-detects from available keys, or override with AI_PROVIDER=gemini|anthropic
AI_PROVIDER = os.environ.get("AI_PROVIDER", "")  # empty = auto-detect

# Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Anthropic (fallback)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
CLASSIFIER_LLM_MODEL = os.environ.get("CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001")

# Embedding model — nomic-embed-text-v1.5 supports Matryoshka dimensions (64, 128, 256, 512, 768)
EMBEDDING_MODEL = os.environ.get("BRAIN_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
EMBEDDING_DIM = 512

# Notion
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")

# Paths (resolve relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent  # scripts/brain-bot/ -> project root
VAULT_PATH = PROJECT_ROOT / "vault"
DB_PATH = PROJECT_ROOT / "data" / "brain.db"
COMMANDS_PATH = PROJECT_ROOT / ".claude" / "commands" / "brain"
CLAUDE_MD_PATH = PROJECT_ROOT / "CLAUDE.md"
NOTION_REGISTRY_PATH = PROJECT_ROOT / "data" / "notion-registry.json"

# Notion Collection IDs
NOTION_COLLECTIONS = {
    "tasks": "collection://231fda46-1a19-8125-95f4-000ba3e22ea6",
    "projects": "collection://231fda46-1a19-8171-9b6d-000b3e3409be",
    "goals": "collection://231fda46-1a19-810f-b0ac-000bbab78a4a",
    "tags": "collection://231fda46-1a19-8195-8338-000b82b65137",
    "notes": "collection://231fda46-1a19-8139-a401-000b477c8cd0",
    "people": "collection://231fda46-1a19-811c-ac4d-000b87d02a66",
}

# Forum topic name -> thread_id mapping (populated from TOPICS_* env vars or at runtime)
# Each topic in the Telegram group replaces a Slack channel.
# Set these after creating forum topics in your group, or configure via env vars.
TOPICS: dict[str, int] = {}
_topic_names = [
    "brain-inbox", "brain-daily", "brain-actions", "brain-dashboard",
    "brain-ideas", "brain-drift", "brain-insights",
    "brain-health", "brain-wealth", "brain-relations",
    "brain-growth", "brain-purpose", "brain-systems",
    "brain-projects", "brain-resources",
]
for _name in _topic_names:
    _env_key = f"TOPIC_{_name.upper().replace('-', '_')}"
    _val = os.environ.get(_env_key, "")
    if _val:
        TOPICS[_name] = int(_val)

# ICOR dimension -> topic mapping (captures go to captures_log table + topic if configured)
DIMENSION_TOPICS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}

# Keywords for quick routing (no AI needed)
DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness", "workout", "diet", "sleep", "exercise", "nutrition", "meditation", "yoga", "running", "gym", "weight", "mental health", "work out", "working out", "well-being", "wellbeing", "calorie", "stretch"],
    "Wealth & Finance": ["money", "finance", "invest", "portfolio", "budget", "savings", "income", "expense", "crypto", "stocks", "salary", "debt", "tax", "side hustle", "net worth", "credit card", "bank account", "real estate"],
    "Relationships": ["friend", "family", "relationship", "dating", "partner", "social", "network", "community", "mentor", "colleague", "hang out", "hanging out", "catch up", "catching up", "get together"],
    "Mind & Growth": ["learn", "read", "book", "course", "study", "skill", "knowledge", "research", "education", "mindset", "philosophy", "psychology", "self improvement", "self-improvement", "personal growth", "online course"],
    "Purpose & Impact": ["career", "mission", "purpose", "impact", "contribute", "volunteer", "leadership", "legacy", "meaning", "values", "give back", "side project", "open source", "passion project"],
    "Systems & Environment": ["system", "automate", "tool", "setup", "organize", "clean", "home", "workspace", "routine", "habit", "process", "workflow", "set up", "setting up", "clean up", "cleaning up", "time management"],
}

# Keywords for cross-posting captures to PARA topics
PROJECT_KEYWORDS = ["project", "milestone", "deadline", "sprint", "deliverable", "launch", "ship", "release", "roadmap", "timeline", "blocker", "blocked", "progress", "phase", "kickoff"]
RESOURCE_KEYWORDS = ["article", "book", "resource", "reference", "template", "tool", "framework", "library", "tutorial", "course", "documentation", "guide", "cheatsheet", "recipe", "podcast", "video", "lecture"]

# Confidence bouncer: messages below this threshold are routed to user DM for clarification
CONFIDENCE_THRESHOLD = float(os.getenv("BRAIN_CONFIDENCE_THRESHOLD", "0.45"))
BOUNCER_TIMEOUT_MINUTES = int(os.getenv("BRAIN_BOUNCER_TIMEOUT", "15"))


def load_dynamic_keywords() -> dict[str, list[str]]:
    """Merge seed keywords with learned keywords from keyword_feedback table.

    Returns a new dict with all keywords per dimension. Learned keywords are
    included only if success_count > fail_count.
    """
    merged = {dim: list(kws) for dim, kws in DIMENSION_KEYWORDS.items()}

    try:
        from core.db_connection import get_connection
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT dimension, keyword FROM keyword_feedback "
                "WHERE success_count > fail_count"
            )
            for row in cursor.fetchall():
                dim, kw = row
                if dim in merged and kw not in merged[dim]:
                    merged[dim].append(kw)
        logger.info("Dynamic keywords loaded: %s", {d: len(v) for d, v in merged.items()})
    except Exception:
        logger.warning("Failed to load dynamic keywords, using seeds only")

    return merged

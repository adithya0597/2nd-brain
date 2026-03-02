"""Configuration for Second Brain Slack Bot."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Slack tokens
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp- token for Socket Mode
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
OWNER_SLACK_ID = os.environ.get("OWNER_SLACK_ID", "")  # Only process messages from owner

# Anthropic
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# Paths (resolve relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent  # scripts/slack-bot/ -> project root
VAULT_PATH = PROJECT_ROOT / "vault"
DB_PATH = PROJECT_ROOT / "data" / "brain.db"
COMMANDS_PATH = PROJECT_ROOT / ".claude" / "commands" / "brain"
CLAUDE_MD_PATH = PROJECT_ROOT / "CLAUDE.md"

# Notion Collection IDs
NOTION_COLLECTIONS = {
    "tasks": "collection://231fda46-1a19-8125-95f4-000ba3e22ea6",
    "projects": "collection://231fda46-1a19-8171-9b6d-000b3e3409be",
    "goals": "collection://231fda46-1a19-810f-b0ac-000bbab78a4a",
    "tags": "collection://231fda46-1a19-8195-8338-000b82b65137",
    "notes": "collection://231fda46-1a19-8139-a401-000b477c8cd0",
    "people": "collection://231fda46-1a19-811c-ac4d-000b87d02a66",
}

# Channel name -> purpose mapping
CHANNELS = {
    "brain-inbox": "Raw capture and routing",
    "brain-daily": "Morning briefings and evening reviews",
    "brain-actions": "Action items with interactive buttons",
    "brain-dashboard": "ICOR heatmap and project status",
    "brain-ideas": "Idea generation reports",
    "brain-drift": "Alignment drift reports",
    "brain-insights": "Pattern synthesis and reflections",
    "brain-health": "Health & Vitality",
    "brain-wealth": "Wealth & Finance",
    "brain-relations": "Relationships",
    "brain-growth": "Mind & Growth",
    "brain-purpose": "Purpose & Impact",
    "brain-systems": "Systems & Environment",
}

# ICOR dimension -> channel mapping (for routing captures)
DIMENSION_CHANNELS = {
    "Health & Vitality": "brain-health",
    "Wealth & Finance": "brain-wealth",
    "Relationships": "brain-relations",
    "Mind & Growth": "brain-growth",
    "Purpose & Impact": "brain-purpose",
    "Systems & Environment": "brain-systems",
}

# Keywords for quick routing (no AI needed)
DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness", "workout", "diet", "sleep", "exercise", "nutrition", "meditation", "yoga", "running", "gym", "weight", "mental health"],
    "Wealth & Finance": ["money", "finance", "invest", "portfolio", "budget", "savings", "income", "expense", "crypto", "stocks", "salary", "debt", "tax"],
    "Relationships": ["friend", "family", "relationship", "dating", "partner", "social", "network", "community", "mentor", "colleague"],
    "Mind & Growth": ["learn", "read", "book", "course", "study", "skill", "knowledge", "research", "education", "mindset", "philosophy", "psychology"],
    "Purpose & Impact": ["career", "mission", "purpose", "impact", "contribute", "volunteer", "leadership", "legacy", "meaning", "values"],
    "Systems & Environment": ["system", "automate", "tool", "setup", "organize", "clean", "home", "workspace", "routine", "habit", "process", "workflow"],
}

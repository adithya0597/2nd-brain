"""Context loading for slash command execution via Anthropic API."""
import json
from pathlib import Path

from .. import config
from . import db_ops, vault_ops

# Map command names to the SQL queries they need
_COMMAND_QUERIES = {
    "context-load": {
        "recent_journal": "SELECT date, summary, mood, energy, icor_elements FROM journal_entries WHERE date >= date('now', '-7 days') ORDER BY date DESC",
        "pending_actions": "SELECT id, description, source_date, icor_element, icor_project FROM action_items WHERE status = 'pending' ORDER BY created_at DESC LIMIT 20",
        "neglected": "SELECT h.name, p.name AS dimension, h.last_mentioned, CAST(julianday('now') - julianday(h.last_mentioned) AS INTEGER) AS days_since FROM icor_hierarchy h JOIN icor_hierarchy p ON h.parent_id = p.id WHERE h.level = 'key_element' AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', '-7 days')) ORDER BY h.last_mentioned ASC NULLS FIRST",
        "concepts": "SELECT title, status, mention_count FROM concept_metadata WHERE status != 'archived' ORDER BY last_mentioned DESC LIMIT 10",
    },
    "today": {
        "pending_actions": "SELECT id, description, source_file, icor_element FROM action_items WHERE status = 'pending' AND source_date <= date('now', '-1 day') ORDER BY source_date DESC",
        "neglected": "SELECT h.name AS key_element, p.name AS dimension, h.last_mentioned, CASE WHEN h.last_mentioned IS NULL THEN 'Never mentioned' ELSE CAST(julianday('now') - julianday(h.last_mentioned) AS INTEGER) || ' days ago' END AS last_activity FROM icor_hierarchy h JOIN icor_hierarchy p ON h.parent_id = p.id WHERE h.level = 'key_element' AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', '-7 days')) ORDER BY h.last_mentioned ASC NULLS FIRST",
        "recent_journal": "SELECT date, summary, mood, energy, icor_elements FROM journal_entries WHERE date >= date('now', '-7 days') ORDER BY date DESC",
    },
    "close-day": {
        "today_journal": "SELECT id, content, mood, energy, icor_elements FROM journal_entries WHERE date = date('now') ORDER BY created_at",
        "pending_actions": "SELECT id, description, source_file, icor_element, icor_project FROM action_items WHERE status = 'pending' ORDER BY created_at DESC",
    },
    "drift": {
        "journal_60d": "SELECT date, content, icor_elements, sentiment_score FROM journal_entries WHERE date >= date('now', '-60 days') ORDER BY date",
        "icor_hierarchy": "SELECT h.id, h.level, h.name, p.name AS parent_name, h.attention_score, h.last_mentioned FROM icor_hierarchy h LEFT JOIN icor_hierarchy p ON h.parent_id = p.id ORDER BY h.id",
        "mention_distribution": "WITH element_mentions AS (SELECT json_each.value AS element_name, COUNT(*) AS mention_count FROM journal_entries, json_each(journal_entries.icor_elements) WHERE journal_entries.date >= date('now', '-30 days') GROUP BY json_each.value) SELECT h.name AS key_element, p.name AS dimension, COALESCE(em.mention_count, 0) AS mentions_30d FROM icor_hierarchy h JOIN icor_hierarchy p ON h.parent_id = p.id LEFT JOIN element_mentions em ON em.element_name = h.name WHERE h.level = 'key_element' ORDER BY mentions_30d DESC",
    },
    "graduate": {
        "graduation_candidates": "SELECT DISTINCT je.icor_elements FROM journal_entries je WHERE je.date >= date('now', '-14 days') AND je.icor_elements != '[]'",
        "concepts": "SELECT title, status, mention_count, last_mentioned, icor_elements, summary FROM concept_metadata WHERE status IN ('seedling', 'growing') ORDER BY last_mentioned DESC",
    },
    "trace": {
        "icor_hierarchy": "SELECT h.id, h.level, h.name, p.name AS parent_name, h.attention_score, h.last_mentioned FROM icor_hierarchy h LEFT JOIN icor_hierarchy p ON h.parent_id = p.id ORDER BY h.id",
        "concepts": "SELECT title, status, mention_count, last_mentioned, first_mentioned, icor_elements, summary FROM concept_metadata WHERE status != 'archived' ORDER BY last_mentioned DESC",
    },
    "ideas": {
        "seedling_concepts": "SELECT title, status, mention_count, last_mentioned, first_mentioned, icor_elements, summary FROM concept_metadata WHERE status IN ('seedling', 'growing') ORDER BY last_mentioned DESC",
        "recurring_themes": "WITH element_freq AS (SELECT json_each.value AS element, COUNT(*) AS freq, MIN(date) AS first_seen, MAX(date) AS last_seen FROM journal_entries, json_each(journal_entries.icor_elements) WHERE date >= date('now', '-60 days') GROUP BY json_each.value) SELECT element, freq, first_seen, last_seen, CAST(julianday(last_seen) - julianday(first_seen) AS INTEGER) AS span_days FROM element_freq WHERE freq >= 3 ORDER BY freq DESC",
        "stale_actions": "SELECT description, source_file, source_date, icor_element, icor_project FROM action_items WHERE status = 'pending' AND source_date <= date('now', '-14 days') ORDER BY source_date ASC",
        "attention_gaps": "SELECT h.name AS element, p.name AS dimension, h.attention_score, COALESCE(ai.mention_count, 0) AS recent_mentions, CASE WHEN h.attention_score > 0 AND COALESCE(ai.mention_count, 0) = 0 THEN 'high_gap' WHEN h.attention_score > COALESCE(ai.attention_score, 0) * 2 THEN 'moderate_gap' ELSE 'aligned' END AS gap_status FROM icor_hierarchy h JOIN icor_hierarchy p ON h.parent_id = p.id LEFT JOIN attention_indicators ai ON ai.icor_element_id = h.id AND ai.period_end = (SELECT MAX(period_end) FROM attention_indicators) WHERE h.level = 'key_element' ORDER BY gap_status, h.attention_score DESC",
    },
    "refresh-dashboard": {
        "attention_scores": "SELECT ai.icor_element_id, h.name, ai.mention_count, ai.journal_days, ai.attention_score, ai.flagged FROM attention_indicators ai JOIN icor_hierarchy h ON ai.icor_element_id = h.id WHERE ai.period_end = (SELECT MAX(period_end) FROM attention_indicators) ORDER BY ai.attention_score DESC",
        "dimensions": "SELECT d.name AS dimension, ke.name AS key_element, ke.attention_score, ke.last_mentioned FROM icor_hierarchy d JOIN icor_hierarchy ke ON ke.parent_id = d.id WHERE d.level = 'dimension' AND ke.level = 'key_element' ORDER BY d.id, ke.id",
        "consistency": "SELECT COUNT(DISTINCT date) AS days_journaled, 30 AS total_days, ROUND(COUNT(DISTINCT date) * 100.0 / 30, 1) AS consistency_pct FROM journal_entries WHERE date >= date('now', '-30 days')",
    },
    "schedule": {
        "energy_patterns": "SELECT CASE CAST(strftime('%w', date) AS INTEGER) WHEN 0 THEN 'Sunday' WHEN 1 THEN 'Monday' WHEN 2 THEN 'Tuesday' WHEN 3 THEN 'Wednesday' WHEN 4 THEN 'Thursday' WHEN 5 THEN 'Friday' WHEN 6 THEN 'Saturday' END AS day_name, CAST(strftime('%w', date) AS INTEGER) AS day_num, COUNT(*) AS entries, ROUND(AVG(CASE energy WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END), 1) AS avg_energy, ROUND(AVG(sentiment_score), 2) AS avg_sentiment, ROUND(AVG(CASE mood WHEN 'great' THEN 5 WHEN 'good' THEN 4 WHEN 'okay' THEN 3 WHEN 'low' THEN 2 WHEN 'bad' THEN 1 END), 1) AS avg_mood FROM journal_entries WHERE date >= date('now', '-90 days') GROUP BY day_num ORDER BY day_num",
        "pending_actions": "SELECT ai.id, ai.description, ai.source_date, ai.icor_element, ai.icor_project, h.name AS element_name, p.name AS dimension_name, CAST(julianday('now') - julianday(ai.source_date) AS INTEGER) AS age_days FROM action_items ai LEFT JOIN icor_hierarchy h ON ai.icor_element = h.name LEFT JOIN icor_hierarchy p ON h.parent_id = p.id WHERE ai.status = 'pending' ORDER BY ai.source_date ASC",
        "dimension_coverage": "SELECT p.name AS dimension, COUNT(DISTINCT ai.id) AS pending_actions, COUNT(DISTINCT CASE WHEN ai.source_date >= date('now', '-7 days') THEN ai.id END) AS recent_actions, MAX(h.attention_score) AS max_attention, MIN(COALESCE(h.last_mentioned, '2000-01-01')) AS oldest_mention FROM icor_hierarchy p LEFT JOIN icor_hierarchy h ON h.parent_id = p.id AND h.level = 'key_element' LEFT JOIN action_items ai ON ai.icor_element = h.name AND ai.status = 'pending' WHERE p.level = 'dimension' GROUP BY p.name ORDER BY pending_actions DESC",
    },
    "emerge": {
        "recent_journal": "SELECT date, content, icor_elements, summary, sentiment_score FROM journal_entries WHERE date >= date('now', '-30 days') ORDER BY date DESC",
        "concepts": "SELECT title, status, mention_count, last_mentioned, icor_elements, summary FROM concept_metadata WHERE status != 'archived' ORDER BY last_mentioned DESC",
    },
}

# Map commands to the vault files they need
_COMMAND_VAULT_FILES = {
    "context-load": [
        "Identity/ICOR.md",
        "Identity/Values.md",
        "Identity/Active-Projects.md",
    ],
    "today": [
        "Identity/ICOR.md",
        "Identity/Active-Projects.md",
    ],
    "close-day": [],
    "drift": [
        "Identity/ICOR.md",
    ],
    "graduate": [],
    "trace": [],
    "ideas": [],
    "ghost": [
        "Identity/ICOR.md",
        "Identity/Values.md",
    ],
    "challenge": [
        "Identity/Values.md",
    ],
    "connect": [],
    "emerge": [],
    "process-inbox": [],
    "process-meeting": [],
    "refresh-dashboard": [],
    "sync-notion": [],
    "schedule": [
        "Identity/ICOR.md",
        "Identity/Active-Projects.md",
    ],
}


def load_command_prompt(command_name: str) -> str:
    """Read the .md prompt file for a slash command."""
    path = config.COMMANDS_PATH / f"{command_name}.md"
    return vault_ops.read_file(path)


def load_system_context() -> str:
    """Read CLAUDE.md for project-level system context."""
    return vault_ops.read_file(config.CLAUDE_MD_PATH)


async def gather_command_context(command_name: str, db_path: Path = None) -> dict:
    """Run relevant SQL queries and read vault files for a command.

    Returns a dict with:
        - "db": dict of query_name -> list[dict] results
        - "vault": dict of relative_path -> file contents
    """
    db_path = db_path or config.DB_PATH
    context = {"db": {}, "vault": {}}

    # Run SQL queries
    queries = _COMMAND_QUERIES.get(command_name, {})
    for name, sql in queries.items():
        try:
            context["db"][name] = await db_ops.query(sql, db_path=db_path)
        except Exception as e:
            context["db"][name] = {"error": str(e)}

    # Read vault files
    vault_files = _COMMAND_VAULT_FILES.get(command_name, [])
    for rel_path in vault_files:
        full_path = config.VAULT_PATH / rel_path
        content = vault_ops.read_file(full_path)
        if content:
            context["vault"][rel_path] = content

    return context


def build_claude_messages(command: str, user_input: str, context: dict) -> list:
    """Construct the messages array for the Anthropic API call.

    Args:
        command: The slash command name (e.g. "today", "drift").
        user_input: Any additional text the user provided.
        context: The dict returned by gather_command_context().

    Returns:
        A list of message dicts suitable for anthropic.messages.create().
    """
    # Build a context block from DB results and vault files
    context_parts = []

    if context.get("vault"):
        for path, content in context["vault"].items():
            context_parts.append(f"### File: {path}\n{content}")

    if context.get("db"):
        for name, rows in context["db"].items():
            if isinstance(rows, dict) and "error" in rows:
                context_parts.append(f"### Query: {name}\nError: {rows['error']}")
            elif rows:
                context_parts.append(f"### Query: {name}\n{json.dumps(rows, indent=2, default=str)}")
            else:
                context_parts.append(f"### Query: {name}\nNo results.")

    context_block = "\n\n".join(context_parts) if context_parts else "No additional context available."

    # Load the command prompt
    prompt = load_command_prompt(command)

    # Build the user message
    user_parts = [f"Execute the /{command} command."]
    if user_input:
        user_parts.append(f"User input: {user_input}")
    user_parts.append(f"\n## Context Data\n{context_block}")

    return [
        {
            "role": "user",
            "content": "\n\n".join(user_parts),
        }
    ]

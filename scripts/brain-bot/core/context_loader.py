"""Context loading for slash command execution via Anthropic API."""
import json
import logging
from pathlib import Path

import config
from core import db_ops, vault_ops

logger = logging.getLogger(__name__)

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
        "mood_energy_7d": """
            SELECT date, mood, energy FROM journal_entries
            WHERE date >= date('now', '-7 days') ORDER BY date DESC
        """,
        "engagement_trend_7d": """
            SELECT date, engagement_score FROM engagement_daily
            WHERE date >= date('now', '-7 days') ORDER BY date DESC
        """,
        "due_actions": """
            SELECT id, description, due_date, status, icor_element, icor_project, source_file, created_at
            FROM action_items
            WHERE due_date IS NOT NULL AND due_date <= date('now') AND status = 'pending'
            ORDER BY due_date ASC
        """,
        "upcoming_actions": """
            SELECT id, description, due_date, status, icor_element, icor_project, source_file, created_at
            FROM action_items
            WHERE due_date IS NOT NULL
              AND due_date > date('now')
              AND due_date <= date('now', '+3 days')
              AND status = 'pending'
            ORDER BY due_date ASC
        """,
    },
    "close-day": {
        "today_journal": "SELECT id, content, mood, energy, icor_elements FROM journal_entries WHERE date = date('now') ORDER BY created_at",
        "pending_actions": "SELECT id, description, source_file, icor_element, icor_project FROM action_items WHERE status = 'pending' ORDER BY created_at DESC",
    },
    "rolling-memo": {
        "today_journal": "SELECT date, summary, mood, energy, icor_elements FROM journal_entries WHERE date = date('now')",
        "recent_captures": "SELECT message_text, dimensions_json, created_at FROM captures_log WHERE date(created_at) = date('now') ORDER BY created_at DESC LIMIT 5",
        "engagement_today": "SELECT engagement_score, captures_count, actions_count FROM engagement_daily WHERE date = date('now')",
    },
    "drift": {
        "journal_60d": "SELECT date, content, icor_elements, sentiment_score FROM journal_entries WHERE date >= date('now', '-60 days') ORDER BY date",
        "icor_hierarchy": "SELECT h.id, h.level, h.name, p.name AS parent_name, h.attention_score, h.last_mentioned FROM icor_hierarchy h LEFT JOIN icor_hierarchy p ON h.parent_id = p.id ORDER BY h.id",
        "mention_distribution": "WITH element_mentions AS (SELECT json_each.value AS element_name, COUNT(*) AS mention_count FROM journal_entries, json_each(journal_entries.icor_elements) WHERE journal_entries.date >= date('now', '-30 days') GROUP BY json_each.value) SELECT h.name AS key_element, p.name AS dimension, COALESCE(em.mention_count, 0) AS mentions_30d FROM icor_hierarchy h JOIN icor_hierarchy p ON h.parent_id = p.id LEFT JOIN element_mentions em ON em.element_name = h.name WHERE h.level = 'key_element' ORDER BY mentions_30d DESC",
    },
    "graduate": {
        "graduation_candidates": "SELECT DISTINCT je.icor_elements FROM journal_entries je WHERE je.date >= date('now', '-14 days') AND je.icor_elements != '[]'",
        "concepts": "SELECT title, status, mention_count, last_mentioned, icor_elements, summary FROM concept_metadata WHERE status IN ('seedling', 'growing') ORDER BY last_mentioned DESC",
        "recent_journal": "SELECT date, content, summary, icor_elements FROM journal_entries WHERE date >= date('now', '-14 days') ORDER BY date DESC",
    },
    "trace": {
        "icor_hierarchy": "SELECT h.id, h.level, h.name, p.name AS parent_name, h.attention_score, h.last_mentioned FROM icor_hierarchy h LEFT JOIN icor_hierarchy p ON h.parent_id = p.id ORDER BY h.id",
        "concepts": "SELECT title, status, mention_count, last_mentioned, first_mentioned, icor_elements, summary FROM concept_metadata WHERE status != 'archived' ORDER BY last_mentioned DESC",
        "concept_timeline": "SELECT title, first_mentioned, last_mentioned, mention_count, status, icor_elements FROM concept_metadata WHERE status != 'archived' ORDER BY first_mentioned ASC",
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
        "mood_energy_30d": """
            SELECT date, mood, energy FROM journal_entries
            WHERE date >= date('now', '-30 days') ORDER BY date DESC
        """,
        "engagement_trend_30d": """
            SELECT date, engagement_score FROM engagement_daily
            WHERE date >= date('now', '-30 days') ORDER BY date DESC
        """,
    },
    "emerge": {
        "recent_journal": "SELECT date, content, icor_elements, summary, sentiment_score FROM journal_entries WHERE date >= date('now', '-30 days') ORDER BY date DESC",
        "concepts": "SELECT title, status, mention_count, last_mentioned, icor_elements, summary FROM concept_metadata WHERE status != 'archived' ORDER BY last_mentioned DESC",
        "orphan_concepts": "SELECT title, file_path, incoming_links_json FROM vault_index WHERE type IN ('concept', '') AND incoming_links_json = '[]' AND outgoing_links_json != '[]'",
    },
    "connect": {
        "vault_graph": "SELECT title, outgoing_links_json, incoming_links_json, type FROM vault_index WHERE outgoing_links_json != '[]' OR incoming_links_json != '[]'",
        "concepts": "SELECT title, status, icor_elements, summary FROM concept_metadata WHERE status != 'archived'",
    },
    "challenge": {
        "values_concepts": "SELECT title, status, mention_count, icor_elements, summary FROM concept_metadata WHERE status != 'archived' AND (icor_elements LIKE '%Purpose%' OR icor_elements LIKE '%Growth%')",
        "journal_beliefs": "SELECT date, content, icor_elements FROM journal_entries WHERE date >= date('now', '-90 days') ORDER BY date DESC",
    },
    "projects": {
        "project_actions": "SELECT icor_project, COUNT(*) AS action_count, SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed FROM action_items WHERE icor_project IS NOT NULL AND icor_project != '' GROUP BY icor_project ORDER BY pending DESC",
        "dimension_project_map": "SELECT p.name AS dimension, h.name AS key_element, ai.icor_project AS project, COUNT(ai.id) AS action_count FROM action_items ai JOIN icor_hierarchy h ON ai.icor_element = h.name JOIN icor_hierarchy p ON h.parent_id = p.id WHERE ai.icor_project IS NOT NULL AND ai.icor_project != '' AND p.level = 'dimension' GROUP BY p.name, h.name, ai.icor_project ORDER BY p.name, action_count DESC",
        "stale_project_actions": "SELECT description, icor_project, icor_element, source_date, CAST(julianday('now') - julianday(source_date) AS INTEGER) AS age_days FROM action_items WHERE status = 'pending' AND icor_project IS NOT NULL AND source_date <= date('now', '-14 days') ORDER BY age_days DESC",
    },
    "resources": {
        "evergreen_concepts": "SELECT title, status, mention_count, last_mentioned, first_mentioned, icor_elements, summary, CAST(julianday('now') - julianday(last_mentioned) AS INTEGER) AS days_since_mention FROM concept_metadata WHERE status IN ('evergreen', 'growing') ORDER BY mention_count DESC",
        "recent_concepts": "SELECT title, status, mention_count, first_mentioned, icor_elements, summary FROM concept_metadata WHERE first_mentioned >= date('now', '-30 days') ORDER BY first_mentioned DESC",
        "stale_concepts": "SELECT title, status, mention_count, last_mentioned, icor_elements, summary, CAST(julianday('now') - julianday(last_mentioned) AS INTEGER) AS days_stale FROM concept_metadata WHERE status != 'archived' AND last_mentioned <= date('now', '-60 days') ORDER BY days_stale DESC",
    },
    "weekly-review": {
        "journal_7d": "SELECT date, content, summary, mood, energy, icor_elements, sentiment_score FROM journal_entries WHERE date >= date('now', '-7 days') ORDER BY date DESC",
        "pending_actions": "SELECT id, description, source_date, status, icor_element, icor_project, CAST(julianday('now') - julianday(source_date) AS INTEGER) AS age_days FROM action_items WHERE status != 'done' ORDER BY created_at DESC",
        "attention": "SELECT dimension, key_element, current_attention FROM attention_indicators ORDER BY dimension",
        "icor_hierarchy": "SELECT h.id, h.level, h.name, p.name AS parent_name, h.attention_score, h.last_mentioned FROM icor_hierarchy h LEFT JOIN icor_hierarchy p ON h.parent_id = p.id ORDER BY h.id",
    },
    "maintain": {
        "orphan_documents": """
            SELECT n.file_path, n.title FROM vault_nodes
            WHERE node_type = 'document'
              AND id NOT IN (
                SELECT DISTINCT source_node_id FROM vault_edges
                UNION SELECT DISTINCT target_node_id FROM vault_edges
              )
            ORDER BY last_modified DESC LIMIT 20
        """,
        "graph_density": "SELECT COUNT(*) AS edges FROM vault_edges",
        "total_nodes": "SELECT COUNT(*) AS cnt FROM vault_nodes WHERE node_type = 'document'",
        "stale_concepts": """
            SELECT file_path, title FROM vault_nodes
            WHERE node_type = 'document' AND type = 'concept'
              AND last_modified < datetime('now', '-60 days')
            ORDER BY last_modified ASC LIMIT 20
        """,
    },
    "engage": {
        "brain_level": """
            SELECT level, consistency_score, breadth_score, depth_score,
                   growth_score, momentum_score, computed_at
            FROM brain_level ORDER BY computed_at DESC LIMIT 1
        """,
        "engagement_7d": """
            SELECT date, engagement_score, journal_entry_count, actions_created,
                   actions_completed, vault_files_modified
            FROM engagement_daily
            ORDER BY date DESC LIMIT 7
        """,
        "dimension_signals": """
            SELECT dimension, rolling_7d_mentions, rolling_7d_captures,
                   momentum, momentum_score, trend, computed_at
            FROM dimension_signals
            WHERE computed_at = (SELECT MAX(computed_at) FROM dimension_signals)
        """,
        "active_alerts": """
            SELECT alert_type, severity, title, details_json, created_at
            FROM alerts WHERE status = 'active'
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END
        """,
        "engagement_30d_avg": """
            SELECT ROUND(AVG(engagement_score), 2) as avg_score,
                   ROUND(AVG(journal_entry_count), 1) as avg_journals,
                   ROUND(AVG(actions_completed), 1) as avg_completed,
                   COUNT(*) as days_tracked
            FROM engagement_daily
            WHERE date >= date('now', '-30 days')
        """,
    },
}

# Parameterized queries for /brain-find — {user_input} is substituted at runtime
_FIND_QUERIES = {
    "journal_matches": "SELECT date, summary, CASE WHEN content LIKE ? THEN 'content' ELSE 'summary' END AS match_type FROM journal_entries WHERE content LIKE ? OR summary LIKE ? ORDER BY date DESC LIMIT 10",
    "concept_matches": "SELECT title, status, mention_count, summary FROM concept_metadata WHERE title LIKE ? OR summary LIKE ? ORDER BY mention_count DESC LIMIT 10",
    "action_matches": "SELECT description, source_date, status, icor_element FROM action_items WHERE description LIKE ? ORDER BY source_date DESC LIMIT 10",
    "vault_matches": "SELECT file_path, title, type, last_modified FROM vault_index WHERE title LIKE ? OR file_path LIKE ? ORDER BY last_modified DESC LIMIT 10",
    "graph_adjacent": "SELECT DISTINCT vi2.file_path, vi2.title, vi2.type FROM vault_index vi1, json_each(vi1.outgoing_links_json) AS link JOIN vault_index vi2 ON vi2.title = link.value WHERE vi1.title LIKE ? OR vi1.file_path LIKE ? LIMIT 10",
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
    "ghost": [  # User-authored identity files only (provenance-safe)
        "Identity/ICOR.md",
        "Identity/Values.md",
    ],
    "challenge": [  # User-authored identity files only (provenance-safe)
        "Identity/Values.md",
        "Identity/ICOR.md",
    ],
    "rolling-memo": [
        "Reports/rolling-memo.md",  # Load prior entries for pattern continuity
    ],
    "connect": [],
    "emerge": [],
    "projects": [
        "Identity/Active-Projects.md",
        "Identity/ICOR.md",
    ],
    "resources": [],
    "process-inbox": [],
    "process-meeting": [],
    "refresh-dashboard": [],
    "sync-notion": [],
    "schedule": [
        "Identity/ICOR.md",
        "Identity/Active-Projects.md",
    ],
    "weekly-review": [
        "Identity/ICOR.md",
        "Identity/Active-Projects.md",
    ],
    "engage": ["Identity/ICOR.md"],
    "maintain": [],
}

# Commands that should get graph context (seed_method, depth)
_GRAPH_CONTEXT_COMMANDS = {
    "trace": {"method": "topic", "depth": 2},
    "connect": {"method": "intersection", "depth": 1},
    "emerge": {"method": "recent_daily", "depth": 1},
    "graduate": {"method": "recent_daily", "depth": 1},
    "ideas": {"method": "recent_daily", "depth": 1},
    # ghost/challenge seed from Identity/ files only — provenance-safe since
    # identity files are user-authored and their wikilink neighbors are unlikely
    # to include Reports/. search_filters.py adds file_types exclusion for any
    # hybrid search that may be added later.
    "ghost": {"method": "identity", "depth": 2},
    "challenge": {"method": "identity", "depth": 1},
    "weekly-review": {"method": "recent_daily", "depth": 1},
}

# Commands that benefit from Notion context
_NOTION_CONTEXT_COMMANDS = {
    "today", "schedule", "ideas", "projects", "close-day",
    "context-load", "drift", "resources", "weekly-review", "engage",
}

# Commands that benefit from pre-computed analytics
_ANALYTICS_COMMANDS = {
    "drift": ["drift_scores"],
    "ideas": ["stale_actions", "co_occurrences", "attention_gaps"],
    "today": ["top3_morning", "stuck_item", "attention_gaps"],
    "schedule": ["attention_gaps", "stale_actions"],
    "emerge": ["co_occurrences"],
}


# Commands that benefit from hybrid search context (replaces graph-only traversal)
_HYBRID_SEARCH_COMMANDS = {
    "find": {"limit": 20},
    "trace": {"limit": 10},
    "ideas": {"limit": 10},
    "connect": {"limit": 10},
}


def _gather_hybrid_context(command_name: str, user_input: str, db_path: Path = None) -> dict[str, str]:
    """Use hybrid search to gather relevant vault files for a command.

    Returns {relative_path: file_content} for top search results.
    Falls back gracefully if search module unavailable.
    """
    search_config = _HYBRID_SEARCH_COMMANDS.get(command_name)
    if not search_config or not user_input:
        return {}

    try:
        from core.search import hybrid_search

        try:
            from core.search_filters import filters_for_command
            metadata_filters = filters_for_command(command_name)
        except ImportError:
            metadata_filters = None

        response = hybrid_search(
            user_input,
            limit=search_config["limit"],
            db_path=db_path,
            metadata_filters=metadata_filters,
            command=command_name,
        )

        result = {}
        for sr in response.results[:15]:
            full_path = config.VAULT_PATH / sr.file_path
            content = vault_ops.read_file(full_path)
            if content:
                result[sr.file_path] = content

        return result
    except Exception:
        logger.debug("Hybrid search context unavailable", exc_info=True)
        return {}


async def _gather_analytics(command_name: str, db_path: Path = None) -> dict:
    """Pre-compute analytics for commands that benefit from them."""
    metrics = _ANALYTICS_COMMANDS.get(command_name)
    if not metrics:
        return {}

    try:
        from core import analytics
    except ImportError:
        logger.warning("analytics module not available")
        return {}

    result = {}
    for metric in metrics:
        try:
            if metric == "drift_scores":
                data = await analytics.compute_drift_scores(db_path=db_path)
                result["drift_scores"] = data[:15]
            elif metric == "stale_actions":
                data = await analytics.detect_stale_actions(db_path=db_path)
                result["stale_actions"] = data[:10]
            elif metric == "co_occurrences":
                data = await analytics.find_co_occurrence_clusters(db_path=db_path)
                result["co_occurrences"] = data[:10]
            elif metric == "attention_gaps":
                data = await analytics.compute_attention_gaps(db_path=db_path)
                result["attention_gaps"] = data[:10]
            elif metric == "top3_morning":
                data = await analytics.compute_top3_morning(db_path=db_path)
                result["top3_morning"] = data
            elif metric == "stuck_item":
                data = await analytics.compute_stuck_item(db_path=db_path)
                if data:
                    result["stuck_item"] = data
        except Exception:
            logger.exception("Failed to compute analytics: %s", metric)

    return result


def load_command_prompt(command_name: str) -> str:
    """Read the .md prompt file for a slash command."""
    path = config.COMMANDS_PATH / f"{command_name}.md"
    return vault_ops.read_file(path)


def load_system_context() -> str:
    """Read CLAUDE.md for project-level system context."""
    return vault_ops.read_file(config.CLAUDE_MD_PATH)


def _load_notion_context() -> dict:
    """Load cached Notion data from the registry JSON file.

    Registry format: {entity_type: {name: {notion_page_id, tag, ...}}}
    Returns a dict with projects, goals keys (each a list of dicts).
    """
    registry_path = config.NOTION_REGISTRY_PATH
    if not registry_path.exists():
        return {}

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read Notion registry at %s", registry_path)
        return {}

    result = {}

    # Extract projects (registry format: {name: {notion_page_id, tag}})
    projects = data.get("projects", {})
    if isinstance(projects, dict) and projects:
        project_list = [
            {"name": name, **info}
            for name, info in projects.items()
            if isinstance(info, dict)
        ]
        if project_list:
            result["projects"] = project_list

    # Extract goals
    goals = data.get("goals", {})
    if isinstance(goals, dict) and goals:
        goal_list = [
            {"name": name, **info}
            for name, info in goals.items()
            if isinstance(info, dict)
        ]
        if goal_list:
            result["goals"] = goal_list

    # Extract dimensions
    dimensions = data.get("dimensions", {})
    if isinstance(dimensions, dict) and dimensions:
        dim_list = [
            {"name": name, **info}
            for name, info in dimensions.items()
            if isinstance(info, dict)
        ]
        if dim_list:
            result["dimensions"] = dim_list

    return result


def _gather_graph_context(command_name: str, user_input: str) -> dict[str, str]:
    """Use the vault index to gather graph-connected files for a command.

    Returns a dict of {relative_path: file_content} for linked files.
    """
    graph_config = _GRAPH_CONTEXT_COMMANDS.get(command_name)
    if not graph_config:
        return {}

    try:
        from core.vault_indexer import (
            cached_find_files_mentioning as find_files_mentioning,
            cached_find_intersection_nodes as find_intersection_nodes,
            cached_get_linked_files as get_linked_files,
        )
    except ImportError:
        logger.warning("vault_indexer not available, skipping graph context")
        return {}

    method = graph_config["method"]
    depth = graph_config["depth"]
    linked_rows = []

    if method == "topic" and user_input:
        # For /trace: find files mentioning the topic, then expand graph
        seed_files = find_files_mentioning(user_input)
        seed_titles = [r["title"] for r in seed_files[:10]]
        if seed_titles:
            linked_rows = get_linked_files(seed_titles, depth=depth)

    elif method == "intersection" and user_input:
        # For /connect: parse "domain A" "domain B" from user input
        # Enhanced: also include bridge nodes connecting communities
        parts = user_input.strip().split('"')
        topics = [p.strip() for p in parts if p.strip()]
        if len(topics) >= 2:
            linked_rows = find_intersection_nodes(topics[0], topics[1])
        elif topics:
            seed_files = find_files_mentioning(topics[0])
            linked_rows = get_linked_files(
                [r["title"] for r in seed_files[:10]], depth=depth,
            )
        try:
            from core.community import get_bridge_nodes
            bridges = get_bridge_nodes(min_communities=2)
            for node in bridges[:5]:
                if node not in linked_rows:
                    node["_hop"] = 99
                    linked_rows.append(node)
        except Exception:
            pass

    elif method == "recent_daily":
        # For /emerge, /graduate, /ideas: start from recent daily notes
        # Enhanced: for /emerge, also include community members
        recent = find_files_mentioning("Daily Notes")
        seed_titles = [r["title"] for r in recent[:7]]
        if seed_titles:
            linked_rows = get_linked_files(seed_titles, depth=depth)
        if command_name == "emerge":
            try:
                from core.community import get_bridge_nodes
                bridges = get_bridge_nodes(min_communities=2)
                for node in bridges[:5]:
                    if node not in linked_rows:
                        node["_hop"] = 99  # mark as bridge
                        linked_rows.append(node)
            except Exception:
                pass

    elif method == "identity":
        # For /ghost, /challenge: start from identity files
        linked_rows = get_linked_files(["ICOR", "Values"], depth=depth)

    # Sort by last_modified for temporal ordering (most recent first)
    # Critical for /trace which needs chronological context
    linked_rows.sort(
        key=lambda r: r.get("last_modified", "") or "", reverse=True
    )

    # Read actual file contents for linked rows
    result = {}
    for row in linked_rows[:15]:  # Cap at 15 files to avoid token overload
        rel_path = row.get("file_path", "")
        if not rel_path:
            continue
        full_path = config.VAULT_PATH / rel_path
        content = vault_ops.read_file(full_path)
        if content:
            result[rel_path] = content

    return result


async def gather_command_context(command_name: str, user_input: str = "", db_path: Path = None, progress_callback=None) -> dict:
    """Run relevant SQL queries, read vault files, and gather graph context.

    Returns a dict with:
        - "db": dict of query_name -> list[dict] results
        - "vault": dict of relative_path -> file contents
        - "notion": dict of entity_type -> list[dict] (if applicable)
        - "graph": dict of relative_path -> file contents (linked files)
    """
    db_path = db_path or config.DB_PATH
    context = {"db": {}, "vault": {}, "notion": {}, "graph": {}}

    # Run SQL queries
    if command_name == "find" and user_input:
        # Parameterized search queries for /brain-find
        like_pattern = f"%{user_input}%"
        for name, sql in _FIND_QUERIES.items():
            try:
                param_count = sql.count("?")
                params = tuple([like_pattern] * param_count)
                context["db"][name] = await db_ops.query(sql, params, db_path=db_path)
            except Exception as e:
                context["db"][name] = {"error": str(e)}
        # Augment with FTS5 ranked search results
        try:
            from core.fts_index import search_fts
            fts_results = search_fts(user_input, limit=15, db_path=str(db_path))
            if fts_results:
                context.setdefault("db", {})["fts_matches"] = fts_results
        except Exception:
            pass  # fallback to existing LIKE queries
    else:
        queries = _COMMAND_QUERIES.get(command_name, {})
        for name, sql in queries.items():
            try:
                context["db"][name] = await db_ops.query(sql, db_path=db_path)
            except Exception as e:
                context["db"][name] = {"error": str(e)}

    if progress_callback:
        progress_callback("db_complete")

    # Read vault files
    vault_files = _COMMAND_VAULT_FILES.get(command_name, [])
    for rel_path in vault_files:
        full_path = config.VAULT_PATH / rel_path
        content = vault_ops.read_file(full_path)
        if content:
            context["vault"][rel_path] = content

    if progress_callback:
        progress_callback("vault_complete")

    # Gather graph-connected vault files
    graph_files = _gather_graph_context(command_name, user_input)
    if graph_files:
        context["graph"] = graph_files

    # Gather hybrid search context (supplements graph context)
    if command_name in _HYBRID_SEARCH_COMMANDS and user_input:
        hybrid_files = _gather_hybrid_context(command_name, user_input, db_path=db_path)
        if hybrid_files:
            # Merge with graph context (hybrid may find additional files)
            for path, content in hybrid_files.items():
                if path not in context.get("graph", {}):
                    context.setdefault("graph", {})[path] = content

    if progress_callback:
        progress_callback("graph_complete")

    # Inject Notion context for applicable commands
    if command_name in _NOTION_CONTEXT_COMMANDS:
        notion_data = _load_notion_context()
        if notion_data:
            context["notion"] = notion_data

    # Inject pre-computed analytics for applicable commands
    analytics = await _gather_analytics(command_name, db_path=db_path)
    if analytics:
        context["analytics"] = analytics

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

    if context.get("graph"):
        context_parts.append("### Linked Vault Files (via graph traversal)")
        for path, content in context["graph"].items():
            # Truncate long files to prevent token overload
            truncated = content[:2000] + "..." if len(content) > 2000 else content
            context_parts.append(f"#### {path}\n{truncated}")

    if context.get("db"):
        for name, rows in context["db"].items():
            if isinstance(rows, dict) and "error" in rows:
                context_parts.append(f"### Query: {name}\nError: {rows['error']}")
            elif rows:
                context_parts.append(f"### Query: {name}\n{json.dumps(rows, indent=2, default=str)}")
            else:
                context_parts.append(f"### Query: {name}\nNo results.")

    if context.get("notion"):
        context_parts.append("### Notion Data (cached)")
        for entity_type, items in context["notion"].items():
            context_parts.append(f"#### {entity_type}\n{json.dumps(items, indent=2, default=str)}")

    if context.get("analytics"):
        context_parts.append("### Pre-Computed Analytics")
        for metric_name, data in context["analytics"].items():
            context_parts.append(f"#### {metric_name}\n{json.dumps(data, indent=2, default=str)}")

    context_block = "\n\n".join(context_parts) if context_parts else "No additional context available."

    # Load the command prompt (used by caller, not needed here)
    load_command_prompt(command)

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

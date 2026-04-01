"""Comprehensive tests for core/formatter.py — all format functions."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.formatter import (
    _e,
    _esc,
    _cb,
    format_morning_briefing,
    format_evening_review,
    format_action_item,
    format_action_list,
    format_capture_confirmation,
    format_classification_feedback,
    format_drift_report,
    format_ideas_report,
    format_projects_dashboard,
    format_resources_catalog,
    format_search_results,
    format_engagement_report,
    format_dashboard,
    format_cost_report,
    format_error,
    format_sync_report,
    format_help,
    format_fading_memories,
)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

class TestUtilities:
    def test_emoji_replacement(self):
        assert "\u26a0\ufe0f" in _e(":warning: alert")

    def test_emoji_passthrough(self):
        assert _e("no emoji here") == "no emoji here"

    def test_esc_html(self):
        assert _esc("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
        assert _esc("a & b") == "a &amp; b"

    def test_cb_compact_json(self):
        result = _cb({"a": "complete", "id": "5"})
        assert '"a":"complete"' in result
        assert " " not in result  # compact, no spaces


# ---------------------------------------------------------------------------
# format_morning_briefing
# ---------------------------------------------------------------------------

class TestMorningBriefing:
    def test_full_data(self):
        data = {
            "date": "2026-04-01",
            "carried_over": [
                {"description": "Fix bug", "icor_element": "Systems"},
                {"description": "Read paper"},
            ],
            "active_projects": [
                {"name": "Brain Bot", "status": "Doing", "goal": "Automate life"},
            ],
            "neglected": [
                {"key_element": "Fitness", "dimension": "Health & Vitality", "last_activity": "14 days ago"},
            ],
            "suggestions": ["Go for a run", "Review vault"],
        }
        html, kb = format_morning_briefing(data)
        assert "Morning Briefing" in html
        assert "2026-04-01" in html
        assert "Fix bug" in html
        assert "Systems" in html
        assert "Brain Bot" in html
        assert "Fitness" in html
        assert "Go for a run" in html
        assert kb is None

    def test_empty_data(self):
        html, kb = format_morning_briefing({})
        assert "Morning Briefing" in html
        assert "clean slate" in html
        assert kb is None

    def test_no_carried_over(self):
        data = {"date": "2026-04-01", "carried_over": []}
        html, _ = format_morning_briefing(data)
        assert "clean slate" in html


# ---------------------------------------------------------------------------
# format_evening_review
# ---------------------------------------------------------------------------

class TestEveningReview:
    def test_full_data(self):
        data = {
            "date": "2026-04-01",
            "completed_actions": [{"description": "Deploy bot"}],
            "new_actions": [{"description": "Write tests"}],
            "journal_summary": "Productive day with focus on code.",
            "mood": "energized",
            "energy": "high",
            "icor_touched": ["Systems", "Mind & Growth"],
            "icor_missed": ["Health & Vitality"],
        }
        html, kb = format_evening_review(data)
        assert "Evening Review" in html
        assert "Deploy bot" in html
        assert "Write tests" in html
        assert "Productive day" in html
        assert "energized" in html
        assert "high" in html
        assert "Systems" in html
        assert "Health &amp; Vitality" in html
        assert kb is None

    def test_empty_review(self):
        html, kb = format_evening_review({})
        assert "Nothing marked complete" in html

    def test_mood_only(self):
        html, _ = format_evening_review({"mood": "calm"})
        assert "calm" in html

    def test_energy_only(self):
        html, _ = format_evening_review({"energy": "low"})
        assert "low" in html


# ---------------------------------------------------------------------------
# format_action_item
# ---------------------------------------------------------------------------

class TestActionItem:
    def test_full_action(self):
        action = {
            "id": "42",
            "description": "Review PR",
            "icor_element": "Systems",
            "icor_project": "Brain Bot",
            "source_date": "2026-04-01",
        }
        html, kb = format_action_item(action)
        assert "Review PR" in html
        assert "Systems" in html
        assert "Brain Bot" in html
        assert "2026-04-01" in html
        assert kb is not None

    def test_minimal_action(self):
        html, kb = format_action_item({"id": "1"})
        assert "No description" in html
        assert kb is not None


# ---------------------------------------------------------------------------
# format_action_list
# ---------------------------------------------------------------------------

class TestActionList:
    def test_empty_list(self):
        html, kb = format_action_list([])
        assert "all clear" in html
        assert kb is None

    def test_with_actions(self):
        actions = [
            {"description": "Task A", "icor_element": "Fitness"},
            {"description": "Task B"},
        ]
        html, kb = format_action_list(actions)
        assert "Pending Actions (2)" in html
        assert "Task A" in html
        assert "Fitness" in html
        assert "Task B" in html


# ---------------------------------------------------------------------------
# format_capture_confirmation
# ---------------------------------------------------------------------------

class TestCaptureConfirmation:
    def test_with_dimensions(self):
        html, _ = format_capture_confirmation("Some thought", ["Health"], ["brain-health"])
        assert "Captured and routed" in html
        assert "Health" in html
        assert "#brain-health" in html

    def test_no_dimensions(self):
        html, _ = format_capture_confirmation("Random thought", [], [])
        assert "inbox" in html.lower()
        assert "No dimension matched" in html

    def test_long_text_truncated(self):
        long_text = "x" * 300
        html, _ = format_capture_confirmation(long_text, ["Health"], ["brain-health"])
        assert "..." in html


# ---------------------------------------------------------------------------
# format_classification_feedback
# ---------------------------------------------------------------------------

class TestClassificationFeedback:
    def test_normal(self):
        html, kb = format_classification_feedback(
            "Working out today", "Health & Vitality", 0.85, "keyword"
        )
        assert "Health &amp; Vitality" in html
        assert "85%" in html
        assert "keyword" in html
        assert kb is not None

    def test_long_text_truncated(self):
        html, _ = format_classification_feedback("y" * 200, "Systems", 0.5, "llm")
        assert "..." in html


# ---------------------------------------------------------------------------
# format_drift_report
# ---------------------------------------------------------------------------

class TestDriftReport:
    def test_full_data(self):
        data = {
            "summary": "Moderate alignment with stated goals.",
            "aligned": [{"element": "Fitness"}],
            "drifted": [{"element": "Reading", "direction": "declining"}],
            "recommendations": ["Read 20 min daily", "Journal about growth"],
        }
        html, kb = format_drift_report(data)
        assert "Drift Report" in html
        assert "Moderate alignment" in html
        assert "Fitness" in html
        assert "Reading" in html
        assert "Read 20 min" in html
        assert kb is None

    def test_empty_drift(self):
        html, _ = format_drift_report({})
        assert "Drift Report" in html


# ---------------------------------------------------------------------------
# format_ideas_report
# ---------------------------------------------------------------------------

class TestIdeasReport:
    def test_with_ideas(self):
        ideas = [
            {"title": "Build a CLI", "description": "A command-line tool for vault", "icor_element": "Systems", "source": "journal 2026-03-30"},
            {"title": "Write article", "description": "Share knowledge"},
        ]
        html, kb = format_ideas_report(ideas)
        assert "Idea Generation" in html
        assert "Build a CLI" in html
        assert "Systems" in html
        assert "journal 2026-03-30" in html
        assert "Write article" in html

    def test_no_ideas(self):
        html, _ = format_ideas_report([])
        assert "No new ideas" in html


# ---------------------------------------------------------------------------
# format_projects_dashboard
# ---------------------------------------------------------------------------

class TestProjectsDashboard:
    def test_full_dashboard(self):
        projects = [
            {"name": "Brain Bot", "status": "Doing", "goal": "Automate life",
             "dimension": "Systems", "done_tasks": 5, "total_tasks": 10,
             "blocked": 2, "deadline": "2026-06-01"},
            {"name": "Reading List", "status": "Ongoing", "goal": "",
             "dimension": "Growth", "done_tasks": 0, "total_tasks": 3,
             "blocked": 0, "deadline": ""},
        ]
        tasks = [
            {"description": "Fix deploy script", "project": "Brain Bot", "age_days": 5},
        ]
        dimensions = [
            {"dimension": "Systems", "project_count": 1, "pending_tasks": 5, "attention_score": 7.5, "status": "Balanced"},
            {"dimension": "Health", "project_count": 0, "pending_tasks": 0, "attention_score": 2.0, "status": "Gap"},
        ]
        html, kb = format_projects_dashboard(projects, tasks, dimensions)
        assert "Project Dashboard" in html
        assert "Brain Bot" in html
        assert "Automate life" in html
        assert "blocked" in html.lower()
        assert "Fix deploy script" in html
        assert kb is None

    def test_empty_dashboard(self):
        html, _ = format_projects_dashboard([], [], [])
        assert "No blocked" in html


# ---------------------------------------------------------------------------
# format_resources_catalog
# ---------------------------------------------------------------------------

class TestResourcesCatalog:
    def test_with_resources(self):
        resources = [
            {"title": "Deep Work", "type": "Book", "dimension": "Growth", "mentions": 5},
            {"title": "Obsidian Guide", "type": "Reference", "dimension": "Systems", "mentions": 2},
        ]
        concepts = [
            {"title": "Focus", "status": "evergreen", "mention_count": 10},
            {"title": "PKM", "status": "growing", "mention_count": 4},
            {"title": "Zettelkasten", "status": "seedling", "mention_count": 1},
        ]
        recently_added = [
            {"title": "New Tool", "type": "Tool", "dimension": "Systems", "date_added": "2026-03-30"},
        ]
        html, kb = format_resources_catalog(resources, concepts, recently_added)
        assert "Knowledge Base" in html
        assert "Deep Work" in html
        assert "Evergreen: 1" in html
        assert "Growing: 1" in html
        assert "Seedling: 1" in html
        assert "New Tool" in html

    def test_empty_catalog(self):
        html, _ = format_resources_catalog([], [], [])
        assert "Knowledge Base" in html


# ---------------------------------------------------------------------------
# format_search_results
# ---------------------------------------------------------------------------

class TestSearchResults:
    def test_with_results(self):
        class FakeResult:
            def __init__(self, title, file_path, snippet, sources):
                self.title = title
                self.file_path = file_path
                self.snippet = snippet
                self.sources = sources

        results = [
            FakeResult("Fitness Notes", "Concepts/Fitness.md", "Body and mind...", ["fts", "vec"]),
            FakeResult("Daily 2026-03-30", "Daily Notes/2026-03-30.md", "Workout day", ["fts"]),
        ]
        html, kb = format_search_results("fitness", results, ["fts", "vec", "graph"], 15)
        assert "fitness" in html
        assert "Fitness Notes" in html
        assert "15 candidates" in html
        assert "2 results" in html

    def test_no_results(self):
        html, _ = format_search_results("nonexistent", [], ["fts"], 0)
        assert "No results found" in html


# ---------------------------------------------------------------------------
# format_engagement_report
# ---------------------------------------------------------------------------

class TestEngagementReport:
    def test_full_report(self):
        data = {
            "brain_level": [{"level": 7}],
            "dimension_signals": [
                {"dimension": "Health", "momentum": "hot", "trend": "rising", "touchpoints": 12},
                {"dimension": "Wealth", "momentum": "frozen", "trend": "declining", "touchpoints": 0},
            ],
            "engagement_7d": [
                {"date": "2026-03-25", "engagement_score": 5.2},
                {"date": "2026-03-26", "engagement_score": 6.1},
            ],
            "active_alerts": [
                {"severity": "warning", "title": "Stale Actions", "detail": "3 actions overdue"},
            ],
            "engagement_30d_avg": [{"avg_score": 5.5, "avg_journals": 0.8, "avg_completed": 2.1, "days_tracked": 28}],
        }
        html, kb = format_engagement_report(data)
        assert "Engagement Dashboard" in html
        assert "Brain Level" in html
        assert "7/10" in html
        assert "Health" in html
        assert "Stale Actions" in html
        assert "30-day avg" in html

    def test_empty_report(self):
        html, _ = format_engagement_report({})
        assert "Engagement Dashboard" in html


# ---------------------------------------------------------------------------
# format_dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_with_data(self):
        icor_data = {
            "Health & Vitality": [
                {"name": "Fitness", "attention_score": 8.0},
                {"name": "Nutrition", "attention_score": 3.0},
            ],
            "Systems": [
                {"name": "Automation", "attention_score": 5.0},
            ],
        }
        projects = [{"name": "Brain Bot", "status": "Doing"}]
        actions = [{"id": 1}, {"id": 2}]
        html, kb = format_dashboard(icor_data, projects, actions)
        assert "ICOR Dashboard" in html
        assert "Fitness" in html
        assert "Brain Bot" in html
        assert "Pending actions: 2" in html

    def test_empty_dashboard(self):
        html, _ = format_dashboard({}, [], [])
        assert "ICOR Dashboard" in html


# ---------------------------------------------------------------------------
# format_cost_report
# ---------------------------------------------------------------------------

class TestCostReport:
    def test_with_data(self):
        data = {
            "daily": [
                {"date": "2026-04-01", "calls": 10, "daily_cost": 0.05, "input_tokens": 5000, "output_tokens": 2000},
                {"date": "2026-03-31", "calls": 5, "daily_cost": 0.02, "input_tokens": 2000, "output_tokens": 800},
            ],
            "by_caller": [
                {"caller": "morning_briefing", "calls": 8, "total_cost": 0.04, "avg_input": 3000, "avg_output": 1500},
            ],
            "by_model": [
                {"model": "claude-sonnet", "calls": 15, "total_cost": 0.07},
            ],
        }
        html, kb = format_cost_report(data, days=7)
        assert "Cost Report" in html
        assert "Last 7 Days" in html
        assert "morning_briefing" in html
        assert "claude-sonnet" in html
        assert kb is None

    def test_empty_data(self):
        html, _ = format_cost_report({})
        assert "No API calls" in html


# ---------------------------------------------------------------------------
# format_error
# ---------------------------------------------------------------------------

class TestFormatError:
    def test_basic_error(self):
        html, kb = format_error("Something went wrong")
        assert "Error" in html
        assert "Something went wrong" in html
        assert kb is None

    def test_html_escape_in_error(self):
        html, _ = format_error("<script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# format_sync_report
# ---------------------------------------------------------------------------

class TestSyncReport:
    def test_success(self):
        result = MagicMock()
        result.errors = []
        result.warnings = []
        result.tasks_pushed = 5
        result.tasks_status_synced = 3
        result.projects_pulled = 2
        result.goals_pulled = 1
        result.tags_synced = 4
        result.notes_pushed = 1
        result.concepts_pushed = 2
        result.people_synced = 0
        result.ai_calls = 1
        html, _ = format_sync_report(result)
        assert "successfully" in html.lower()
        assert "Tasks pushed: 5" in html
        assert "Projects pulled: 2" in html

    def test_with_errors(self):
        result = MagicMock()
        result.errors = ["Task push failed: timeout"]
        result.warnings = ["Stale project detected"]
        result.tasks_pushed = 0
        result.tasks_status_synced = 0
        result.projects_pulled = 0
        result.goals_pulled = 0
        result.tags_synced = 0
        result.notes_pushed = 0
        result.concepts_pushed = 0
        result.people_synced = 0
        result.ai_calls = 0
        html, _ = format_sync_report(result)
        assert "errors" in html.lower()
        assert "Task push failed" in html
        assert "Stale project detected" in html

    def test_no_changes(self):
        result = MagicMock()
        result.errors = []
        result.warnings = []
        result.tasks_pushed = 0
        result.tasks_status_synced = 0
        result.projects_pulled = 0
        result.goals_pulled = 0
        result.tags_synced = 0
        result.notes_pushed = 0
        result.concepts_pushed = 0
        result.people_synced = 0
        result.ai_calls = 0
        html, _ = format_sync_report(result)
        assert "in sync" in html.lower()


# ---------------------------------------------------------------------------
# format_help
# ---------------------------------------------------------------------------

class TestHelp:
    def test_help_output(self):
        html, kb = format_help()
        assert "Second Brain Commands" in html
        assert "/brain-today" in html
        assert "/brain-drift" in html
        assert kb is None


# ---------------------------------------------------------------------------
# format_fading_memories
# ---------------------------------------------------------------------------

class TestFadingMemories:
    def test_with_items(self):
        items = [
            {"title": "Old Concept", "days_old": 45, "edge_count": 5, "file_path": "Concepts/Old.md"},
            {"title": "Stale Note", "days_old": 60, "edge_count": 3, "file_path": "Notes/Stale.md"},
        ]
        html, kb = format_fading_memories(items)
        assert "Fading Memories" in html
        assert "Old Concept" in html
        assert "45d" in html
        assert kb is not None

    def test_empty_items(self):
        html, kb = format_fading_memories([])
        assert html == ""
        assert kb is None

"""Tests for core/notion_mappers.py — pure Notion property transforms."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.notion_mappers import (
    extract_title,
    extract_rich_text,
    extract_select,
    extract_status,
    extract_multi_select,
    extract_relation,
    extract_date,
    extract_checkbox,
    extract_number,
    build_title_property,
    build_rich_text_property,
    build_select_property,
    build_status_property,
    build_multi_select_property,
    build_relation_property,
    build_date_property,
    build_checkbox_property,
    build_number_property,
    action_to_notion_task,
    notion_task_to_action,
    notion_project_to_local,
    notion_goal_to_local,
    icor_element_to_notion_tag,
    notion_tag_to_icor,
    journal_to_notion_note,
    concept_to_notion_note,
    notion_person_to_local,
)


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

class TestExtractTitle:
    def test_normal(self):
        props = {"Name": {"title": [{"text": {"content": "My Task"}}]}}
        assert extract_title(props) == "My Task"

    def test_empty(self):
        assert extract_title({}) == ""

    def test_custom_key(self):
        props = {"Title": {"title": [{"text": {"content": "Custom"}}]}}
        assert extract_title(props, key="Title") == "Custom"

    def test_empty_title_list(self):
        props = {"Name": {"title": []}}
        assert extract_title(props) == ""


class TestExtractRichText:
    def test_normal(self):
        props = {"Desc": {"rich_text": [{"text": {"content": "Hello"}}]}}
        assert extract_rich_text(props, "Desc") == "Hello"

    def test_empty(self):
        assert extract_rich_text({}, "Desc") == ""

    def test_empty_list(self):
        props = {"Desc": {"rich_text": []}}
        assert extract_rich_text(props, "Desc") == ""


class TestExtractSelect:
    def test_normal(self):
        props = {"Type": {"select": {"name": "Area"}}}
        assert extract_select(props, "Type") == "Area"

    def test_none(self):
        assert extract_select({}, "Type") is None

    def test_no_select(self):
        props = {"Type": {"select": None}}
        assert extract_select(props, "Type") is None


class TestExtractStatus:
    def test_normal(self):
        props = {"Status": {"status": {"name": "Doing"}}}
        assert extract_status(props, "Status") == "Doing"

    def test_none(self):
        assert extract_status({}, "Status") is None


class TestExtractMultiSelect:
    def test_normal(self):
        props = {"Tags": {"multi_select": [{"name": "A"}, {"name": "B"}]}}
        assert extract_multi_select(props, "Tags") == ["A", "B"]

    def test_empty(self):
        assert extract_multi_select({}, "Tags") == []


class TestExtractRelation:
    def test_normal(self):
        props = {"Goal": {"relation": [{"id": "abc"}, {"id": "def"}]}}
        assert extract_relation(props, "Goal") == ["abc", "def"]

    def test_empty(self):
        assert extract_relation({}, "Goal") == []


class TestExtractDate:
    def test_normal(self):
        props = {"Due": {"date": {"start": "2026-04-01"}}}
        assert extract_date(props, "Due") == "2026-04-01"

    def test_none(self):
        assert extract_date({}, "Due") is None

    def test_no_date(self):
        props = {"Due": {"date": None}}
        assert extract_date(props, "Due") is None


class TestExtractCheckbox:
    def test_true(self):
        props = {"Archived": {"checkbox": True}}
        assert extract_checkbox(props, "Archived") is True

    def test_false(self):
        props = {"Archived": {"checkbox": False}}
        assert extract_checkbox(props, "Archived") is False

    def test_missing(self):
        assert extract_checkbox({}, "Archived") is False


class TestExtractNumber:
    def test_normal(self):
        props = {"Score": {"number": 42.5}}
        assert extract_number(props, "Score") == 42.5

    def test_none(self):
        assert extract_number({}, "Score") is None


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

class TestBuilders:
    def test_build_title(self):
        result = build_title_property("Test")
        assert result["title"][0]["text"]["content"] == "Test"

    def test_build_rich_text(self):
        result = build_rich_text_property("Hello")
        assert result["rich_text"][0]["text"]["content"] == "Hello"

    def test_build_select(self):
        result = build_select_property("Area")
        assert result["select"]["name"] == "Area"

    def test_build_status(self):
        result = build_status_property("Doing")
        assert result["status"]["name"] == "Doing"

    def test_build_multi_select(self):
        result = build_multi_select_property(["A", "B"])
        assert len(result["multi_select"]) == 2
        assert result["multi_select"][0]["name"] == "A"

    def test_build_relation(self):
        result = build_relation_property(["id1", "id2"])
        assert len(result["relation"]) == 2
        assert result["relation"][0]["id"] == "id1"

    def test_build_date(self):
        result = build_date_property("2026-04-01")
        assert result["date"]["start"] == "2026-04-01"

    def test_build_checkbox(self):
        assert build_checkbox_property(True) == {"checkbox": True}
        assert build_checkbox_property(False) == {"checkbox": False}

    def test_build_number(self):
        assert build_number_property(3.14) == {"number": 3.14}


# ---------------------------------------------------------------------------
# Entity transforms
# ---------------------------------------------------------------------------

class TestActionToNotionTask:
    def test_basic(self):
        action = {"description": "Fix bug", "status": "pending"}
        registry = {}
        result = action_to_notion_task(action, registry)
        assert result["Name"]["title"][0]["text"]["content"] == "Fix bug"
        assert result["Status"]["status"]["name"] == "To Do"

    def test_with_project(self):
        action = {"description": "Deploy", "status": "in_progress", "icor_project": "Brain Bot"}
        registry = {"projects": {"Brain Bot": {"notion_page_id": "proj-123"}}}
        result = action_to_notion_task(action, registry)
        assert result["Project"]["relation"][0]["id"] == "proj-123"
        assert result["Status"]["status"]["name"] == "Doing"

    def test_with_icor_element(self):
        action = {"description": "Read paper", "status": "completed", "icor_element": "Mind & Growth"}
        registry = {}
        result = action_to_notion_task(action, registry)
        assert "ICOR: Mind & Growth" in result["Description"]["rich_text"][0]["text"]["content"]


class TestNotionTaskToAction:
    def test_basic(self):
        page = {
            "id": "page-123",
            "properties": {
                "Name": {"title": [{"text": {"content": "Fix bug"}}]},
                "Status": {"status": {"name": "Done"}},
                "Priority": {"status": {"name": "High"}},
                "Due": {"date": {"start": "2026-04-01"}},
            },
            "last_edited_time": "2026-04-01T10:00:00Z",
        }
        result = notion_task_to_action(page)
        assert result["notion_id"] == "page-123"
        assert result["description"] == "Fix bug"
        assert result["status"] == "completed"
        assert result["priority"] == "High"
        assert result["due_date"] == "2026-04-01"


class TestNotionProjectToLocal:
    def test_full(self):
        page = {
            "id": "proj-1",
            "properties": {
                "Name": {"title": [{"text": {"content": "Brain Bot"}}]},
                "Status": {"status": {"name": "Doing"}},
                "Tag": {"relation": [{"id": "tag-1"}]},
                "Goal": {"relation": [{"id": "goal-1"}]},
                "Target Deadline": {"date": {"start": "2026-06-01"}},
                "Archived": {"checkbox": False},
            },
            "last_edited_time": "2026-04-01T10:00:00Z",
        }
        result = notion_project_to_local(page)
        assert result["name"] == "Brain Bot"
        assert result["status"] == "Doing"
        assert result["tag_ids"] == ["tag-1"]
        assert result["goal_ids"] == ["goal-1"]
        assert result["archived"] is False


class TestNotionGoalToLocal:
    def test_full(self):
        page = {
            "id": "goal-1",
            "properties": {
                "Name": {"title": [{"text": {"content": "Automate life"}}]},
                "Status": {"status": {"name": "Active"}},
                "Tag": {"relation": [{"id": "tag-2"}]},
                "Target Deadline": {"date": {"start": "2026-12-31"}},
                "Archived": {"checkbox": False},
            },
            "last_edited_time": "2026-04-01T10:00:00Z",
        }
        result = notion_goal_to_local(page)
        assert result["name"] == "Automate life"
        assert result["status"] == "Active"


class TestIcorElementToNotionTag:
    def test_dimension(self):
        element = {"name": "Health & Vitality"}
        result = icor_element_to_notion_tag(element)
        assert result["Name"]["title"][0]["text"]["content"] == "Health & Vitality"
        assert result["Type"]["select"]["name"] == "Area"
        assert "Parent Tag" not in result

    def test_with_parent(self):
        element = {"name": "Fitness"}
        result = icor_element_to_notion_tag(element, parent_notion_id="parent-123")
        assert result["Parent Tag"]["relation"][0]["id"] == "parent-123"


class TestNotionTagToIcor:
    def test_full(self):
        page = {
            "id": "tag-1",
            "properties": {
                "Name": {"title": [{"text": {"content": "Health & Vitality"}}]},
                "Type": {"select": {"name": "Area"}},
                "Parent Tag": {"relation": []},
                "Sub-Tags": {"relation": [{"id": "sub-1"}]},
                "Archived": {"checkbox": False},
            },
            "last_edited_time": "2026-04-01T10:00:00Z",
        }
        result = notion_tag_to_icor(page)
        assert result["name"] == "Health & Vitality"
        assert result["type"] == "Area"
        assert result["sub_tag_ids"] == ["sub-1"]


class TestJournalToNotionNote:
    def test_basic(self):
        entry = {"date": "2026-04-01", "mood": "energized", "energy": "high", "icor_elements": ""}
        registry = {}
        result = journal_to_notion_note(entry, registry)
        assert "Daily" in result["Name"]["title"][0]["text"]["content"]
        assert "2026-04-01" in result["Name"]["title"][0]["text"]["content"]
        assert "energized" in result["Name"]["title"][0]["text"]["content"]

    def test_no_date(self):
        entry = {"date": "", "mood": "", "energy": "", "icor_elements": ""}
        result = journal_to_notion_note(entry, {})
        assert "Note Date" not in result

    def test_with_icor_elements(self):
        entry = {"date": "2026-04-01", "mood": "", "energy": "", "icor_elements": "Fitness, Income"}
        registry = {
            "key_elements": {"Fitness": {"notion_page_id": "ke-1"}},
            "dimensions": {"Income": {"notion_page_id": "dim-2"}},
        }
        result = journal_to_notion_note(entry, registry)
        assert "Tag" in result
        assert len(result["Tag"]["relation"]) >= 1


class TestConceptToNotionNote:
    def test_seedling(self):
        concept = {"name": "PKM", "status": "seedling", "mention_count": 3, "last_mentioned": "2026-03-30", "icor_elements": ""}
        result = concept_to_notion_note(concept, {})
        assert "PKM" in result["Name"]["title"][0]["text"]["content"]
        assert result["Type"]["select"]["name"] == "Idea"
        assert "Note Date" in result

    def test_evergreen(self):
        concept = {"name": "Focus", "status": "evergreen", "mention_count": 20, "last_mentioned": "", "icor_elements": ""}
        result = concept_to_notion_note(concept, {})
        assert result["Type"]["select"]["name"] == "Reference"

    def test_with_icor(self):
        concept = {"name": "Diet", "status": "growing", "mention_count": 5, "last_mentioned": "2026-03-30", "icor_elements": "Nutrition"}
        registry = {"key_elements": {"Nutrition": {"notion_page_id": "ke-nut"}}}
        result = concept_to_notion_note(concept, registry)
        assert "Tag" in result
        assert result["Tag"]["relation"][0]["id"] == "ke-nut"


class TestNotionPersonToLocal:
    def test_full(self):
        page = {
            "id": "person-1",
            "properties": {
                "Full Name": {"title": [{"text": {"content": "John Doe"}}]},
                "Relationship": {"select": {"name": "Friend"}},
                "Email": {"rich_text": [{"text": {"content": "john@example.com"}}]},
                "Phone": {"rich_text": [{"text": {"content": "+1234567890"}}]},
                "Company": {"rich_text": [{"text": {"content": "Acme Inc"}}]},
                "Tags": {"relation": [{"id": "tag-1"}]},
                "Birthday": {"date": {"start": "1990-05-15"}},
                "Last Check-In": {"date": {"start": "2026-03-15"}},
            },
            "last_edited_time": "2026-04-01T10:00:00Z",
        }
        result = notion_person_to_local(page)
        assert result["name"] == "John Doe"
        assert result["relationship"] == "Friend"
        assert result["email"] == "john@example.com"
        assert result["phone"] == "+1234567890"
        assert result["company"] == "Acme Inc"
        assert result["birthday"] == "1990-05-15"
        assert result["last_checkin"] == "2026-03-15"

    def test_minimal(self):
        page = {
            "id": "person-2",
            "properties": {
                "Full Name": {"title": [{"text": {"content": "Jane"}}]},
            },
            "last_edited_time": "",
        }
        result = notion_person_to_local(page)
        assert result["name"] == "Jane"
        assert result["email"] == ""

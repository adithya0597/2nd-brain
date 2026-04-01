"""Tests for core/output_parser.py — Parse structured output from Claude AI responses."""
import sys
from pathlib import Path

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

from core.output_parser import parse_graduate_output


# ---------------------------------------------------------------------------
# JSON block parsing
# ---------------------------------------------------------------------------


class TestParseGraduateOutputJSON:

    def test_parse_valid_json_block_with_multiple_concepts(self):
        result_text = """Here are the recurring themes I found:

```json
{
  "concepts": [
    {
      "title": "Morning-Routines",
      "summary": "Establishing consistent morning routines for productivity",
      "icor_elements": ["Health & Vitality", "Systems & Environment"],
      "status": "seedling",
      "source_dates": ["2026-03-01", "2026-03-03", "2026-03-05"],
      "first_mentioned": "2026-03-01",
      "last_mentioned": "2026-03-05",
      "mention_count": 3
    },
    {
      "title": "Deep-Work-Blocks",
      "summary": "Scheduling uninterrupted focus time for cognitively demanding tasks",
      "icor_elements": ["Mind & Growth"],
      "status": "seedling",
      "source_dates": ["2026-02-28", "2026-03-02"],
      "first_mentioned": "2026-02-28",
      "last_mentioned": "2026-03-02",
      "mention_count": 2
    }
  ]
}
```

These concepts appeared frequently in your recent journal entries."""

        concepts = parse_graduate_output(result_text)
        assert len(concepts) == 2

        assert concepts[0].title == "Morning-Routines"
        assert concepts[0].summary == "Establishing consistent morning routines for productivity"
        assert concepts[0].icor_elements == ["Health & Vitality", "Systems & Environment"]
        assert concepts[0].status == "seedling"
        assert concepts[0].source_dates == ["2026-03-01", "2026-03-03", "2026-03-05"]
        assert concepts[0].first_mentioned == "2026-03-01"
        assert concepts[0].last_mentioned == "2026-03-05"
        assert concepts[0].mention_count == 3

        assert concepts[1].title == "Deep-Work-Blocks"
        assert concepts[1].icor_elements == ["Mind & Growth"]
        assert concepts[1].mention_count == 2

    def test_parse_empty_concepts_array(self):
        result_text = """No recurring themes found.

```json
{
  "concepts": []
}
```
"""
        concepts = parse_graduate_output(result_text)
        assert concepts == []

    def test_parse_malformed_json_returns_empty(self):
        result_text = """Here are some themes:

```json
{this is not valid json at all
```

Some more text after the broken block."""

        concepts = parse_graduate_output(result_text)
        assert concepts == []

    def test_concept_fields_have_correct_defaults(self):
        result_text = """```json
{
  "concepts": [
    {
      "title": "Minimal-Concept",
      "summary": "Just a summary"
    }
  ]
}
```"""
        concepts = parse_graduate_output(result_text)
        assert len(concepts) == 1
        c = concepts[0]
        assert c.title == "Minimal-Concept"
        assert c.summary == "Just a summary"
        assert c.icor_elements == []
        assert c.status == "seedling"
        assert c.source_dates == []
        assert c.first_mentioned == ""
        assert c.last_mentioned == ""
        assert c.mention_count == 1


# ---------------------------------------------------------------------------
# Markdown fallback parsing
# ---------------------------------------------------------------------------


class TestParseGraduateOutputMarkdown:

    def test_parse_markdown_headers_fallback(self):
        result_text = """# Graduation Report

I found these recurring themes:

### Concept 1: Morning-Routines

- **Summary:** Establishing consistent morning routines for productivity
- **ICOR Elements:** Health & Vitality, Systems & Environment
- **Sources:** 2026-03-01, 2026-03-03, 2026-03-05

### Concept 2: Deep-Work-Blocks

- **Summary:** Scheduling uninterrupted focus time
- **ICOR Elements:** Mind & Growth
- **Sources:** 2026-02-28, 2026-03-02
"""

        concepts = parse_graduate_output(result_text)
        assert len(concepts) == 2

        assert concepts[0].title == "Morning-Routines"
        assert concepts[0].summary == "Establishing consistent morning routines for productivity"
        assert concepts[0].icor_elements == ["Health & Vitality", "Systems & Environment"]
        assert concepts[0].source_dates == ["2026-03-01", "2026-03-03", "2026-03-05"]
        assert concepts[0].first_mentioned == "2026-03-01"
        assert concepts[0].last_mentioned == "2026-03-05"
        assert concepts[0].mention_count == 3

        assert concepts[1].title == "Deep-Work-Blocks"
        assert concepts[1].icor_elements == ["Mind & Growth"]
        assert concepts[1].mention_count == 2

    def test_markdown_concept_without_optional_fields(self):
        result_text = """### Concept 1: Bare-Minimum

Just some description text.
"""
        concepts = parse_graduate_output(result_text)
        assert len(concepts) == 1
        assert concepts[0].title == "Bare-Minimum"
        assert concepts[0].summary == "Concept graduated from daily notes"
        assert concepts[0].icor_elements == []
        assert concepts[0].source_dates == []

    def test_no_concepts_found_returns_empty(self):
        result_text = """No recurring themes were identified in the last 14 days.
Try journaling more consistently to build patterns."""

        concepts = parse_graduate_output(result_text)
        assert concepts == []

    def test_json_preferred_over_markdown(self):
        """When both JSON and markdown are present, JSON wins."""
        result_text = """### Concept 1: Markdown-Version

- **Summary:** From markdown

```json
{
  "concepts": [
    {
      "title": "JSON-Version",
      "summary": "From JSON"
    }
  ]
}
```
"""
        concepts = parse_graduate_output(result_text)
        assert len(concepts) == 1
        assert concepts[0].title == "JSON-Version"


# ---------------------------------------------------------------------------
# Integration test: parse -> create_concept_file -> insert_concept_metadata
# ---------------------------------------------------------------------------


class TestGraduationIntegration:

    @pytest.fixture(autouse=True)
    def _patch_config(self, mock_config):
        yield

    def test_end_to_end_graduation(self, temp_vault, test_db):
        """Parse graduate output, create concept files, insert DB rows."""
        import asyncio
        from core.vault_ops import create_concept_file
        from core.db_ops import insert_concept_metadata, query

        result_text = """```json
{
  "concepts": [
    {
      "title": "Morning-Routines",
      "summary": "Establishing consistent morning routines",
      "icor_elements": ["Health & Vitality"],
      "status": "seedling",
      "source_dates": ["2026-03-01", "2026-03-03"],
      "first_mentioned": "2026-03-01",
      "last_mentioned": "2026-03-03",
      "mention_count": 2
    },
    {
      "title": "Deep-Work-Blocks",
      "summary": "Scheduling uninterrupted focus time",
      "icor_elements": ["Mind & Growth"],
      "status": "seedling",
      "source_dates": ["2026-02-28"],
      "first_mentioned": "2026-02-28",
      "last_mentioned": "2026-02-28",
      "mention_count": 1
    }
  ]
}
```"""

        concepts = parse_graduate_output(result_text)
        assert len(concepts) == 2

        created_files = []
        for concept in concepts:
            file_path = create_concept_file(
                name=concept.title,
                summary=concept.summary,
                source_notes=concept.source_dates,
                icor_elements=concept.icor_elements,
                status=concept.status,
            )
            assert file_path.exists()
            created_files.append(file_path)

            rel_path = str(file_path.relative_to(temp_vault))
            asyncio.run(insert_concept_metadata(
                title=concept.title,
                file_path=rel_path,
                icor_elements=concept.icor_elements,
                first_mentioned=concept.first_mentioned,
                last_mentioned=concept.last_mentioned,
                mention_count=concept.mention_count,
                summary=concept.summary,
                status=concept.status,
                db_path=test_db,
            ))

        # Verify vault files
        assert (temp_vault / "Concepts" / "Morning-Routines.md").exists()
        assert (temp_vault / "Concepts" / "Deep-Work-Blocks.md").exists()

        content = (temp_vault / "Concepts" / "Morning-Routines.md").read_text()
        assert "# Morning-Routines" in content
        assert "Establishing consistent morning routines" in content
        assert "[[Health & Vitality]]" in content
        assert "[[2026-03-01]]" in content

        # Verify DB rows
        rows = asyncio.run(query(
            "SELECT title, file_path, status, icor_elements, mention_count "
            "FROM concept_metadata ORDER BY title",
            db_path=test_db,
        ))
        assert len(rows) == 2
        assert rows[0]["title"] == "Deep-Work-Blocks"
        assert rows[0]["status"] == "seedling"
        assert rows[0]["mention_count"] == 1
        assert rows[1]["title"] == "Morning-Routines"
        assert rows[1]["mention_count"] == 2

    def test_duplicate_concept_ignored(self, temp_vault, test_db):
        """INSERT OR IGNORE prevents duplicate concept_metadata rows."""
        import asyncio
        from core.db_ops import insert_concept_metadata, query

        # Insert twice with the same title
        for _ in range(2):
            asyncio.run(insert_concept_metadata(
                title="Duplicate-Concept",
                file_path="Concepts/Duplicate-Concept.md",
                icor_elements=["Mind & Growth"],
                first_mentioned="2026-03-01",
                mention_count=1,
                summary="Test",
                db_path=test_db,
            ))

        rows = asyncio.run(query(
            "SELECT COUNT(*) AS cnt FROM concept_metadata WHERE title = 'Duplicate-Concept'",
            db_path=test_db,
        ))
        assert rows[0]["cnt"] == 1

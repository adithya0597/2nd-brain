"""Tests for core/journal_indexer.py — Daily note parsing and indexing."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing journal_indexer (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

from core.journal_indexer import (
    _detect_mood,
    _detect_energy,
    _detect_icor_elements,
    _extract_frontmatter,
    _strip_frontmatter,
    _generate_summary,
    parse_daily_note,
    scan_daily_notes,
    index_to_db,
    run_full_index,
)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

class TestFrontmatterParsing:

    def test_extract_valid_frontmatter(self):
        content = "---\ntype: journal\ndate: 2026-03-06\n---\n\nBody text."
        fm = _extract_frontmatter(content)
        assert fm["type"] == "journal"
        # YAML auto-parses date-like strings to datetime.date objects
        from datetime import date
        assert fm["date"] == date(2026, 3, 6)

    def test_extract_no_frontmatter(self):
        content = "Just plain text with no frontmatter."
        fm = _extract_frontmatter(content)
        assert fm == {}

    def test_strip_frontmatter(self):
        content = "---\ntype: journal\n---\n\nBody text here."
        stripped = _strip_frontmatter(content)
        assert "type: journal" not in stripped
        assert "Body text here." in stripped

    def test_strip_no_frontmatter(self):
        content = "No frontmatter in this file."
        stripped = _strip_frontmatter(content)
        assert stripped == "No frontmatter in this file."


# ---------------------------------------------------------------------------
# Mood detection
# ---------------------------------------------------------------------------

class TestMoodDetection:

    def test_great_mood(self):
        mood = _detect_mood("Had an amazing day, everything was wonderful!", {})
        assert mood == "great"

    def test_good_mood(self):
        mood = _detect_mood("Feeling happy and productive today.", {})
        assert mood == "good"

    def test_okay_mood(self):
        mood = _detect_mood("Things were fine, just an okay day overall.", {})
        assert mood == "okay"

    def test_low_mood(self):
        mood = _detect_mood("Feeling really tired and stressed out.", {})
        assert mood == "low"

    def test_bad_mood(self):
        mood = _detect_mood("Terrible day, feeling miserable about everything.", {})
        assert mood == "bad"

    def test_frontmatter_overrides_content(self):
        mood = _detect_mood("Terrible awful day", {"mood": "great"})
        assert mood == "great"

    def test_no_mood_detected(self):
        mood = _detect_mood("Went to the store and bought some supplies.", {})
        assert mood == ""

    def test_strongest_mood_wins(self):
        """When multiple mood words appear, the most frequent category wins."""
        # Two 'great' words vs one 'good' word
        mood = _detect_mood("Amazing and wonderful day, also good.", {})
        assert mood == "great"


# ---------------------------------------------------------------------------
# Energy detection
# ---------------------------------------------------------------------------

class TestEnergyDetection:

    def test_high_energy(self):
        energy = _detect_energy("Feeling energized and motivated to tackle the day!", {})
        assert energy == "high"

    def test_medium_energy(self):
        energy = _detect_energy("Energy levels are moderate and steady today.", {})
        assert energy == "medium"

    def test_low_energy(self):
        energy = _detect_energy("Totally exhausted and drained after yesterday.", {})
        assert energy == "low"

    def test_frontmatter_overrides_content(self):
        energy = _detect_energy("Exhausted and drained", {"energy": "high"})
        assert energy == "high"

    def test_no_energy_detected(self):
        energy = _detect_energy("Picked up groceries on the way home.", {})
        assert energy == ""


# ---------------------------------------------------------------------------
# ICOR element extraction
# ---------------------------------------------------------------------------

class TestICORExtraction:

    def test_health_detection(self):
        elements = _detect_icor_elements("Did a workout at the gym this morning.", {})
        assert "Health & Vitality" in elements

    def test_finance_detection(self):
        elements = _detect_icor_elements("Need to review my budget and check investments.", {})
        assert "Wealth & Finance" in elements

    def test_relationships_detection(self):
        elements = _detect_icor_elements("Had dinner with family tonight.", {})
        assert "Relationships" in elements

    def test_growth_detection(self):
        elements = _detect_icor_elements("Started reading a new book about creativity.", {})
        assert "Mind & Growth" in elements

    def test_purpose_detection(self):
        elements = _detect_icor_elements("Working on my career goals and leadership skills.", {})
        assert "Purpose & Impact" in elements

    def test_systems_detection(self):
        elements = _detect_icor_elements("Setting up a new workflow to automate tasks.", {})
        assert "Systems & Environment" in elements

    def test_multiple_dimensions(self):
        elements = _detect_icor_elements(
            "Went to the gym in the morning, then studied for my course. "
            "Had dinner with family and reviewed my budget.", {}
        )
        assert "Health & Vitality" in elements
        assert "Mind & Growth" in elements
        assert "Relationships" in elements
        assert "Wealth & Finance" in elements

    def test_frontmatter_overrides(self):
        fm = {"icor_elements": ["Custom Element"]}
        elements = _detect_icor_elements("gym workout exercise", fm)
        assert elements == ["Custom Element"]

    def test_no_elements_detected(self):
        elements = _detect_icor_elements("The weather was nice today.", {})
        assert elements == []

    def test_results_are_sorted(self):
        elements = _detect_icor_elements("gym and money and friend", {})
        assert elements == sorted(elements)


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

class TestSummaryGeneration:

    def test_summary_from_first_paragraph(self):
        content = "---\ntype: journal\n---\n\n# Title\n\nThis is the first meaningful line."
        summary = _generate_summary(content)
        assert summary == "This is the first meaningful line."

    def test_summary_truncation(self):
        long_line = "A" * 300
        content = f"---\ntype: journal\n---\n\n{long_line}"
        summary = _generate_summary(content, max_length=200)
        assert len(summary) <= 204  # 200 + "..."
        assert summary.endswith("...")

    def test_summary_skips_headings(self):
        content = "# Heading\n## Subheading\nActual content here."
        summary = _generate_summary(content)
        assert summary == "Actual content here."


# ---------------------------------------------------------------------------
# parse_daily_note (full file parsing)
# ---------------------------------------------------------------------------

class TestParseDailyNote:

    def test_parse_valid_note(self, tmp_path):
        note = tmp_path / "2026-03-06.md"
        note.write_text(
            "---\ntype: journal\ndate: 2026-03-06\n---\n\n"
            "# Friday, March 6, 2026\n\n"
            "Feeling happy and productive today. Went to the gym for a workout.\n"
            "Also reviewed my budget. Need to call family tomorrow.\n",
            encoding="utf-8",
        )
        result = parse_daily_note(note)
        assert result is not None
        assert result["date"] == "2026-03-06"
        assert result["mood"] == "good"
        assert "Health & Vitality" in result["icor_elements"]
        assert "Wealth & Finance" in result["icor_elements"]
        assert isinstance(result["summary"], str)

    def test_parse_too_short_note(self, tmp_path):
        note = tmp_path / "2026-03-06.md"
        note.write_text("---\ntype: journal\n---\n\nShort.", encoding="utf-8")
        result = parse_daily_note(note)
        assert result is None  # Body < 20 chars

    def test_parse_invalid_date_filename(self, tmp_path):
        note = tmp_path / "not-a-date.md"
        note.write_text("---\ntype: journal\n---\n\nSome longer content here for parsing.", encoding="utf-8")
        result = parse_daily_note(note)
        assert result is None

    def test_parse_missing_file(self, tmp_path):
        result = parse_daily_note(tmp_path / "nonexistent.md")
        assert result is None


# ---------------------------------------------------------------------------
# scan_daily_notes
# ---------------------------------------------------------------------------

class TestScanDailyNotes:

    def test_scan_empty_directory(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "Daily Notes").mkdir()
        entries = scan_daily_notes(vault)
        assert entries == []

    def test_scan_with_valid_notes(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        notes_dir = vault / "Daily Notes"
        notes_dir.mkdir()

        for day in ["2026-03-04", "2026-03-05", "2026-03-06"]:
            (notes_dir / f"{day}.md").write_text(
                f"---\ntype: journal\ndate: {day}\n---\n\n"
                f"# {day}\n\nThis is a decent journal entry for the day with enough content.\n",
                encoding="utf-8",
            )

        entries = scan_daily_notes(vault)
        assert len(entries) == 3
        dates = [e["date"] for e in entries]
        assert "2026-03-04" in dates
        assert "2026-03-05" in dates
        assert "2026-03-06" in dates

    def test_scan_nonexistent_directory(self, tmp_path):
        vault = tmp_path / "no-vault"
        entries = scan_daily_notes(vault)
        assert entries == []


# ---------------------------------------------------------------------------
# index_to_db (write to SQLite)
# ---------------------------------------------------------------------------

class TestIndexToDb:

    def test_index_entries_to_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                content TEXT,
                mood TEXT,
                energy TEXT,
                icor_elements TEXT DEFAULT '[]',
                summary TEXT,
                sentiment_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

        entries = [
            {
                "date": "2026-03-06",
                "content": "Test content",
                "mood": "good",
                "energy": "high",
                "icor_elements": ["Health & Vitality"],
                "summary": "A test entry",
                "sentiment_score": 0.0,
            }
        ]
        index_to_db(entries, db_file)

        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("SELECT date, mood, energy FROM journal_entries").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "2026-03-06"
        assert rows[0][1] == "good"
        assert rows[0][2] == "high"

    def test_upsert_updates_existing(self, tmp_path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                content TEXT,
                mood TEXT,
                energy TEXT,
                icor_elements TEXT DEFAULT '[]',
                summary TEXT,
                sentiment_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

        entry1 = {
            "date": "2026-03-06",
            "content": "Original content",
            "mood": "okay",
            "energy": "low",
            "icor_elements": [],
            "summary": "Original",
            "sentiment_score": 0.0,
        }
        index_to_db([entry1], db_file)

        entry2 = {
            "date": "2026-03-06",
            "content": "Updated content",
            "mood": "great",
            "energy": "high",
            "icor_elements": ["Health & Vitality"],
            "summary": "Updated",
            "sentiment_score": 0.5,
        }
        index_to_db([entry2], db_file)

        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("SELECT date, mood, content FROM journal_entries").fetchall()
        conn.close()
        assert len(rows) == 1  # Still just one row
        assert rows[0][1] == "great"
        assert rows[0][2] == "Updated content"


# ---------------------------------------------------------------------------
# run_full_index (integration)
# ---------------------------------------------------------------------------

class TestRunFullIndex:

    def test_full_index_pipeline(self, tmp_path):
        # Set up vault with daily notes
        vault = tmp_path / "vault"
        vault.mkdir()
        notes_dir = vault / "Daily Notes"
        notes_dir.mkdir()

        (notes_dir / "2026-03-06.md").write_text(
            "---\ntype: journal\ndate: 2026-03-06\n---\n\n"
            "# March 6\n\nFeeling good today. Went to the gym for a workout.\n",
            encoding="utf-8",
        )

        # Set up DB
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                content TEXT,
                mood TEXT,
                energy TEXT,
                icor_elements TEXT DEFAULT '[]',
                summary TEXT,
                sentiment_score REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

        count = run_full_index(vault_path=vault, db_path=db_file)
        assert count == 1

        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("SELECT date, mood FROM journal_entries").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "2026-03-06"
        assert rows[0][1] == "good"

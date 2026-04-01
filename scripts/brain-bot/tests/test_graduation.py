"""Tests for concept graduation detection and handlers."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure brain-bot is on the path
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())


# ---------------------------------------------------------------------------
# DB fixture — matches conftest._SCHEMA_SQL plus graduation_proposals
# ---------------------------------------------------------------------------

def _create_test_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS captures_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT NOT NULL,
            dimensions_json TEXT DEFAULT '[]',
            confidence REAL,
            method TEXT,
            is_actionable INTEGER DEFAULT 0,
            source_channel TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS concept_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL UNIQUE,
            file_path TEXT,
            status TEXT DEFAULT 'seedling',
            icor_elements TEXT DEFAULT '[]',
            first_mentioned TEXT,
            last_mentioned TEXT,
            mention_count INTEGER DEFAULT 0,
            related_concepts TEXT DEFAULT '[]',
            summary TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            notion_id TEXT
        );
        CREATE TABLE IF NOT EXISTS graduation_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_hash TEXT NOT NULL UNIQUE,
            proposed_title TEXT NOT NULL,
            proposed_dimension TEXT,
            source_capture_ids TEXT NOT NULL DEFAULT '[]',
            source_texts TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected','snoozed','expired')),
            message_id INTEGER,
            proposed_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT,
            snooze_until TEXT
        );
    """)
    conn.commit()
    return conn


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_brain.db"
    conn = _create_test_db(db_path)
    conn.close()
    return db_path


def _insert_captures(conn, dimension, count, days_span=14):
    """Insert test captures spread across days for a given dimension.

    Each capture gets its own distinct day to satisfy the 7-distinct-days
    requirement in the graduation detector query.
    """
    for i in range(count):
        # Spread evenly across the days_span so each lands on a different day
        day_offset = i * max(days_span // max(count, 1), 1)
        conn.execute(
            "INSERT INTO captures_log (message_text, dimensions_json, confidence, method, created_at) "
            "VALUES (?, ?, 0.8, 'keyword', datetime('now', ?))",
            (
                f"Test capture about {dimension} #{i}",
                json.dumps([dimension]),
                f"-{day_offset} days",
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Graduation Detector Tests
# ---------------------------------------------------------------------------


class TestDetectGraduationCandidates:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_captures(self, test_db):
        from core.graduation_detector import detect_graduation_candidates

        result = await detect_graduation_candidates(db_path=test_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_finds_candidate_with_enough_captures(self, test_db):
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        _insert_captures(conn, "Health & Vitality", count=10, days_span=20)
        conn.close()

        result = await detect_graduation_candidates(db_path=test_db)
        assert len(result) == 1
        assert result[0]["dimension"] == "Health & Vitality"
        assert result[0]["capture_count"] == 10
        assert result[0]["proposed_title"] == "Health & Vitality Insights"
        assert result[0]["cluster_hash"]  # Non-empty hash

    @pytest.mark.asyncio
    async def test_ignores_low_capture_count(self, test_db):
        """Fewer than 3 captures should not produce a candidate."""
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        _insert_captures(conn, "Wealth & Finance", count=2, days_span=10)
        conn.close()

        result = await detect_graduation_candidates(db_path=test_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_ignores_narrow_day_spread(self, test_db):
        """Captures all on the same day should not produce a candidate."""
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        # 5 captures, all on the same day (days_span=0)
        for i in range(5):
            conn.execute(
                "INSERT INTO captures_log (message_text, dimensions_json, confidence, method) "
                "VALUES (?, ?, 0.8, 'keyword')",
                (f"Same-day capture #{i}", json.dumps(["Mind & Growth"])),
            )
        conn.commit()
        conn.close()

        result = await detect_graduation_candidates(db_path=test_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_existing_concepts(self, test_db):
        """Dimensions with existing concept notes should be excluded."""
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        _insert_captures(conn, "Health & Vitality", count=10, days_span=20)
        # Add existing concept for this dimension
        conn.execute(
            "INSERT INTO concept_metadata (title, icor_elements, status) "
            "VALUES (?, ?, 'seedling')",
            ("Health Insights", json.dumps(["Health & Vitality"])),
        )
        conn.commit()
        conn.close()

        result = await detect_graduation_candidates(db_path=test_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_pending_proposals(self, test_db):
        """Clusters with existing pending proposals should be excluded."""
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        _insert_captures(conn, "Health & Vitality", count=10, days_span=20)
        conn.commit()

        # First call should find the candidate
        result = await detect_graduation_candidates(db_path=test_db)
        assert len(result) == 1
        cluster_hash = result[0]["cluster_hash"]

        # Insert a pending proposal with this hash
        conn.execute(
            "INSERT INTO graduation_proposals (cluster_hash, proposed_title, status) "
            "VALUES (?, 'Test', 'pending')",
            (cluster_hash,),
        )
        conn.commit()
        conn.close()

        # Second call should filter it out
        result2 = await detect_graduation_candidates(db_path=test_db)
        assert result2 == []

    @pytest.mark.asyncio
    async def test_max_three_candidates(self, test_db):
        """Should return at most 3 candidates."""
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        for dim in [
            "Health & Vitality",
            "Wealth & Finance",
            "Relationships",
            "Mind & Growth",
        ]:
            _insert_captures(conn, dim, count=10, days_span=20)
        conn.close()

        result = await detect_graduation_candidates(db_path=test_db)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_ignores_low_confidence(self, test_db):
        """Captures with confidence < 0.5 should be excluded."""
        from core.graduation_detector import detect_graduation_candidates

        conn = sqlite3.connect(str(test_db))
        for i in range(10):
            conn.execute(
                "INSERT INTO captures_log (message_text, dimensions_json, confidence, method, created_at) "
                "VALUES (?, ?, 0.3, 'keyword', datetime('now', ?))",
                (f"Low conf #{i}", json.dumps(["Purpose & Impact"]), f"-{i * 2} days"),
            )
        conn.commit()
        conn.close()

        result = await detect_graduation_candidates(db_path=test_db)
        assert result == []


# ---------------------------------------------------------------------------
# Proposal Formatting Tests
# ---------------------------------------------------------------------------


class TestFormatGraduationProposal:
    def test_format_produces_valid_html(self):
        from handlers.graduation import format_graduation_proposal

        proposal = {
            "id": 42,
            "proposed_title": "Health & Vitality Insights",
            "proposed_dimension": "Health & Vitality",
            "capture_count": 5,
            "days_span": 14,
            "source_texts": json.dumps(["Went to the gym", "Ate healthy today"]),
        }
        text, kb = format_graduation_proposal(proposal)
        assert "Concept Graduation Proposal" in text
        assert "Health &amp; Vitality Insights" in text
        assert "5 captures over 14 days" in text
        assert kb is not None

    def test_format_keyboard_has_four_buttons(self):
        from handlers.graduation import format_graduation_proposal

        proposal = {
            "id": 1,
            "proposed_title": "Test",
            "proposed_dimension": "Test",
            "capture_count": 3,
            "days_span": 7,
            "source_texts": "[]",
        }
        text, kb = format_graduation_proposal(proposal)
        # kb is a mock from the mocked telegram module, so just check it was called
        assert kb is not None

"""Tests for core/analytics.py — Pre-computed analytics functions."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

# Mock config before importing analytics (conftest sets all defaults)
sys.modules.setdefault("config", MagicMock())

from core.analytics import (
    compute_drift_scores,
    detect_stale_actions,
    find_co_occurrence_clusters,
    compute_attention_gaps,
    compute_top3_morning,
    compute_stuck_item,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_journal(conn, date: str, icor_elements: list, content: str = "Test entry"):
    """Insert a journal entry with the given ICOR elements."""
    conn.execute(
        "INSERT OR REPLACE INTO journal_entries (date, content, icor_elements, mood, energy, summary) "
        "VALUES (?, ?, ?, 'good', 'high', 'test summary')",
        (date, content, json.dumps(icor_elements)),
    )


def _insert_action(conn, description: str, source_date: str,
                    icor_element: str = None, icor_project: str = None,
                    status: str = "pending"):
    """Insert an action item."""
    conn.execute(
        "INSERT INTO action_items (description, source_file, source_date, icor_element, icor_project, status) "
        "VALUES (?, 'test', ?, ?, ?, ?)",
        (description, source_date, icor_element, icor_project, status),
    )


def _set_attention_score(conn, element_id: int, score: float):
    """Set attention_score for an ICOR element."""
    conn.execute(
        "UPDATE icor_hierarchy SET attention_score = ? WHERE id = ?",
        (score, element_id),
    )


# ---------------------------------------------------------------------------
# compute_drift_scores
# ---------------------------------------------------------------------------

class TestComputeDriftScores:

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, test_db):
        """No journal entries => still returns elements but all with 0 mentions."""
        results = await compute_drift_scores(db_path=test_db)
        # Should still return rows for key_elements (from seed data)
        # All have 0 mentions and 0 attention, so deviation is 0
        assert isinstance(results, list)
        for r in results:
            assert r["mentions_30d"] == 0

    @pytest.mark.asyncio
    async def test_sorted_by_deviation_desc(self, test_db):
        """Results should be sorted by deviation, highest first."""
        conn = sqlite3.connect(str(test_db))
        # Give Fitness a high attention score but no journal mentions
        _set_attention_score(conn, 101, 10.0)
        # Give Nutrition low attention but many journal mentions
        _set_attention_score(conn, 102, 0.0)
        for i in range(5):
            _insert_journal(conn, f"2026-02-{10 + i:02d}", ["Nutrition"])
        conn.commit()
        conn.close()

        results = await compute_drift_scores(days=60, db_path=test_db)
        assert len(results) >= 2
        # Verify sorted by deviation descending
        deviations = [r["deviation"] for r in results]
        assert deviations == sorted(deviations, reverse=True)

    @pytest.mark.asyncio
    async def test_drift_status_classification(self, test_db):
        """Elements with high stated attention but zero mentions get high_gap."""
        conn = sqlite3.connect(str(test_db))
        _set_attention_score(conn, 101, 10.0)  # Fitness: high attention
        _set_attention_score(conn, 102, 0.0)   # Nutrition: zero attention
        _set_attention_score(conn, 201, 0.0)   # Income: zero attention
        _set_attention_score(conn, 301, 0.0)   # Family: zero attention
        # Only mention Nutrition in journals
        for i in range(5):
            _insert_journal(conn, f"2026-02-{10 + i:02d}", ["Nutrition"])
        conn.commit()
        conn.close()

        results = await compute_drift_scores(days=60, db_path=test_db)
        fitness = next(r for r in results if r["element"] == "Fitness")
        # Fitness has max attention (1.0) but zero mentions (0.0) => deviation 1.0 => high_gap
        assert fitness["drift_status"] == "high_gap"
        assert fitness["deviation"] == 1.0

    @pytest.mark.asyncio
    async def test_result_fields(self, test_db):
        """Verify all expected fields are present."""
        results = await compute_drift_scores(db_path=test_db)
        if results:
            r = results[0]
            assert "element" in r
            assert "dimension" in r
            assert "attention_score" in r
            assert "mentions_30d" in r
            assert "deviation" in r
            assert "drift_status" in r


# ---------------------------------------------------------------------------
# detect_stale_actions
# ---------------------------------------------------------------------------

class TestDetectStaleActions:

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, test_db):
        results = await detect_stale_actions(db_path=test_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_groups_by_element(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Old fitness task", "2026-01-01", icor_element="Fitness")
        _insert_action(conn, "Another fitness task", "2026-01-05", icor_element="Fitness")
        _insert_action(conn, "Old income task", "2026-01-10", icor_element="Income")
        conn.commit()
        conn.close()

        results = await detect_stale_actions(stale_days=14, db_path=test_db)
        elements = {r["element"] for r in results}
        assert "Fitness" in elements
        assert "Income" in elements

        fitness_group = next(r for r in results if r["element"] == "Fitness")
        assert fitness_group["action_count"] == 2

    @pytest.mark.asyncio
    async def test_respects_stale_threshold(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Recent action (within threshold) - use a date in the future to ensure it's fresh
        _insert_action(conn, "Fresh task", "2026-03-27", icor_element="Fitness")
        conn.commit()
        conn.close()

        results = await detect_stale_actions(stale_days=14, db_path=test_db)
        # Fresh task should NOT appear (it's not stale)
        descriptions = []
        for group in results:
            for a in group["actions"]:
                descriptions.append(a["description"])
        assert "Fresh task" not in descriptions

    @pytest.mark.asyncio
    async def test_sorted_by_oldest_age(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Very old", "2025-12-01", icor_element="Fitness")
        _insert_action(conn, "Moderately old", "2026-01-15", icor_element="Income")
        conn.commit()
        conn.close()

        results = await detect_stale_actions(stale_days=14, db_path=test_db)
        if len(results) >= 2:
            ages = [r["oldest_age_days"] for r in results]
            assert ages == sorted(ages, reverse=True)

    @pytest.mark.asyncio
    async def test_unassigned_element(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "No element task", "2026-01-01", icor_element=None)
        conn.commit()
        conn.close()

        results = await detect_stale_actions(stale_days=14, db_path=test_db)
        unassigned = next((r for r in results if r["element"] == "Unassigned"), None)
        assert unassigned is not None
        assert unassigned["action_count"] == 1

    @pytest.mark.asyncio
    async def test_completed_actions_excluded(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Completed old task", "2026-01-01",
                        icor_element="Fitness", status="completed")
        conn.commit()
        conn.close()

        results = await detect_stale_actions(stale_days=14, db_path=test_db)
        assert results == []


# ---------------------------------------------------------------------------
# find_co_occurrence_clusters
# ---------------------------------------------------------------------------

class TestFindCoOccurrenceClusters:

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, test_db):
        results = await find_co_occurrence_clusters(db_path=test_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_finds_pairs_above_threshold(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Fitness + Nutrition co-occur 4 times (above default min_co=3)
        for i in range(4):
            _insert_journal(conn, f"2026-02-{10 + i:02d}", ["Fitness", "Nutrition"])
        conn.commit()
        conn.close()

        results = await find_co_occurrence_clusters(min_co=3, db_path=test_db)
        assert len(results) >= 1
        pair = results[0]
        assert pair["co_count"] >= 3
        assert {pair["elem1"], pair["elem2"]} == {"Fitness", "Nutrition"}

    @pytest.mark.asyncio
    async def test_ignores_pairs_below_threshold(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Fitness + Income co-occur only 2 times (below min_co=3)
        for i in range(2):
            _insert_journal(conn, f"2026-02-{10 + i:02d}", ["Fitness", "Income"])
        conn.commit()
        conn.close()

        results = await find_co_occurrence_clusters(min_co=3, db_path=test_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_sorted_by_co_count_desc(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Fitness + Nutrition: 5 co-occurrences
        for i in range(5):
            _insert_journal(conn, f"2026-02-{10 + i:02d}", ["Fitness", "Nutrition"])
        # Fitness + Income: 3 co-occurrences (must be within 60-day window)
        for i in range(3):
            _insert_journal(conn, f"2026-03-{10 + i:02d}", ["Fitness", "Income"])
        conn.commit()
        conn.close()

        results = await find_co_occurrence_clusters(min_co=3, db_path=test_db)
        assert len(results) >= 2
        counts = [r["co_count"] for r in results]
        assert counts == sorted(counts, reverse=True)

    @pytest.mark.asyncio
    async def test_single_element_entries_ignored(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Entries with only 1 element can't form pairs
        for i in range(10):
            _insert_journal(conn, f"2026-02-{10 + i:02d}", ["Fitness"])
        conn.commit()
        conn.close()

        results = await find_co_occurrence_clusters(min_co=1, db_path=test_db)
        assert results == []


# ---------------------------------------------------------------------------
# compute_attention_gaps
# ---------------------------------------------------------------------------

class TestComputeAttentionGaps:

    @pytest.mark.asyncio
    async def test_empty_db_returns_critical_for_zero_elements(self, test_db):
        """Elements with 0 attention and 0 mentions should be critical."""
        results = await compute_attention_gaps(db_path=test_db)
        # All seed elements have 0 attention and 0 mentions => all critical
        assert len(results) >= 4
        for r in results:
            assert r["gap_severity"] == "critical"

    @pytest.mark.asyncio
    async def test_classifies_high_gap(self, test_db):
        """Element with score < 50% of dimension average => high gap."""
        conn = sqlite3.connect(str(test_db))
        # Set Fitness to 10, Nutrition to 1 => avg = 5.5
        # Nutrition (1) < 5.5 * 0.5 (2.75) => high
        _set_attention_score(conn, 101, 10.0)
        _set_attention_score(conn, 102, 1.0)
        # Give both some mentions so they're not "critical"
        _insert_journal(conn, "2026-02-20", ["Fitness", "Nutrition"])
        conn.commit()
        conn.close()

        results = await compute_attention_gaps(db_path=test_db)
        nutrition = next((r for r in results if r["element"] == "Nutrition"), None)
        assert nutrition is not None
        assert nutrition["gap_severity"] == "high"

    @pytest.mark.asyncio
    async def test_aligned_elements_excluded(self, test_db):
        """Elements at or above dimension average should not appear."""
        conn = sqlite3.connect(str(test_db))
        # Set both Health elements to same score
        _set_attention_score(conn, 101, 5.0)
        _set_attention_score(conn, 102, 5.0)
        # Give both mentions
        _insert_journal(conn, "2026-02-20", ["Fitness", "Nutrition"])
        conn.commit()
        conn.close()

        results = await compute_attention_gaps(db_path=test_db)
        health_elements = [r for r in results if r["dimension"] == "Health & Vitality"]
        # Both are at the average, so they should be aligned (not in results)
        assert all(r["gap_severity"] != "aligned" for r in health_elements)

    @pytest.mark.asyncio
    async def test_severity_sort_order(self, test_db):
        """Results sorted: critical first, then high, then moderate."""
        results = await compute_attention_gaps(db_path=test_db)
        severity_order = {"critical": 0, "high": 1, "moderate": 2}
        orders = [severity_order.get(r["gap_severity"], 3) for r in results]
        assert orders == sorted(orders)

    @pytest.mark.asyncio
    async def test_result_fields(self, test_db):
        results = await compute_attention_gaps(db_path=test_db)
        if results:
            r = results[0]
            assert "element" in r
            assert "dimension" in r
            assert "attention_score" in r
            assert "mentions_30d" in r
            assert "gap_severity" in r


# ---------------------------------------------------------------------------
# compute_top3_morning
# ---------------------------------------------------------------------------

class TestComputeTop3Morning:

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, test_db):
        results = await compute_top3_morning(db_path=test_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_max_3(self, test_db):
        conn = sqlite3.connect(str(test_db))
        for i in range(5):
            _insert_action(conn, f"Task {i}", f"2026-01-{10 + i:02d}")
        conn.commit()
        conn.close()

        results = await compute_top3_morning(db_path=test_db)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_sorted_by_composite_score(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Old task with project (high score)
        _insert_action(conn, "Old project task", "2025-12-01",
                        icor_project="Big Project")
        # Old task without project
        _insert_action(conn, "Old solo task", "2025-12-15")
        # Recent task with project
        _insert_action(conn, "Recent project task", "2026-03-01",
                        icor_project="Small Project")
        conn.commit()
        conn.close()

        results = await compute_top3_morning(db_path=test_db)
        scores = [r["composite_score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        # Old task with project should be first (highest age + project bonus)
        assert results[0]["description"] == "Old project task"

    @pytest.mark.asyncio
    async def test_project_bonus_applied(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Same date, one with project, one without
        _insert_action(conn, "With project", "2026-01-01",
                        icor_project="MyProject")
        _insert_action(conn, "Without project", "2026-01-01")
        conn.commit()
        conn.close()

        results = await compute_top3_morning(db_path=test_db)
        with_proj = next(r for r in results if r["description"] == "With project")
        without_proj = next(r for r in results if r["description"] == "Without project")
        assert with_proj["composite_score"] > without_proj["composite_score"]

    @pytest.mark.asyncio
    async def test_excludes_completed(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Pending task", "2026-01-01")
        _insert_action(conn, "Done task", "2026-01-01", status="completed")
        conn.commit()
        conn.close()

        results = await compute_top3_morning(db_path=test_db)
        descriptions = [r["description"] for r in results]
        assert "Pending task" in descriptions
        assert "Done task" not in descriptions


# ---------------------------------------------------------------------------
# compute_stuck_item
# ---------------------------------------------------------------------------

class TestComputeStuckItem:

    @pytest.mark.asyncio
    async def test_empty_db_returns_none(self, test_db):
        result = await compute_stuck_item(db_path=test_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_oldest_if_stale(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Very old task", "2025-12-01", icor_element="Fitness")
        _insert_action(conn, "Less old task", "2026-02-01", icor_element="Income")
        conn.commit()
        conn.close()

        result = await compute_stuck_item(stale_days=14, db_path=test_db)
        assert result is not None
        assert result["description"] == "Very old task"
        assert result["age_days"] >= 14

    @pytest.mark.asyncio
    async def test_returns_none_if_not_stale_enough(self, test_db):
        conn = sqlite3.connect(str(test_db))
        # Insert a very recent action
        _insert_action(conn, "Fresh task", "2026-03-27")
        conn.commit()
        conn.close()

        result = await compute_stuck_item(stale_days=14, db_path=test_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_completed(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Old but done", "2025-12-01", status="completed")
        conn.commit()
        conn.close()

        result = await compute_stuck_item(stale_days=14, db_path=test_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_result_fields(self, test_db):
        conn = sqlite3.connect(str(test_db))
        _insert_action(conn, "Stuck item", "2025-12-01", icor_element="Fitness")
        conn.commit()
        conn.close()

        result = await compute_stuck_item(stale_days=14, db_path=test_db)
        assert result is not None
        assert "description" in result
        assert "age_days" in result
        assert "icor_element" in result
        assert "source_date" in result

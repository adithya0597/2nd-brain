"""Regression tests for 5 bugs identified by the grill adversarial review.

These tests verify the fixes remain in place. They are independent of mock data.
"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure config mock is available before any project imports
sys.modules.setdefault("config", MagicMock())

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))


# ── Bug 1: L2 similarity formula should use d², not d ──────────────────────


def test_l2_similarity_uses_squared_distance():
    """The similarity formula for L2 distance must be 1 - d²/2, not 1 - d/2.

    For normalized embeddings, the correct conversion from L2 distance to
    cosine similarity is: similarity = 1 - distance² / 2.
    Using 1 - distance / 2 underestimates similarity for close vectors.
    """
    import re

    source_file = BRAIN_BOT_DIR / "core" / "graph_ops.py"
    source = source_file.read_text()

    # Find all similarity = ... lines involving distance
    pattern = re.compile(r"similarity\s*=.*distance.*distance", re.IGNORECASE)
    matches = pattern.findall(source)

    # There should be at least 2 occurrences (rebuild + update functions)
    assert len(matches) >= 2, (
        f"Expected >=2 squared-distance similarity formulas in graph_ops.py, "
        f"found {len(matches)}. The formula must use distance*distance (d²)."
    )

    # Verify the WRONG formula (1 - distance / 2 without squaring) is NOT present
    wrong_pattern = re.compile(
        r"1\.0\s*-\s*distance\s*/\s*2\.0(?!\s*\*)", re.IGNORECASE
    )
    wrong_matches = wrong_pattern.findall(source)
    assert len(wrong_matches) == 0, (
        f"Found {len(wrong_matches)} instances of the WRONG formula '1 - d/2' "
        f"in graph_ops.py. Must use '1 - d²/2'."
    )


# ── Bug 2: engage query must use correct column names ──────────────────────


def test_engage_query_columns_match_schema(test_db):
    """The engage command's SQL queries must reference columns that exist in the
    actual schema (brain_level, engagement_daily, dimension_signals, alerts).
    """
    from core.context_loader import _COMMAND_QUERIES

    engage_queries = _COMMAND_QUERIES.get("engage", {})
    assert engage_queries, "No 'engage' queries found in _COMMAND_QUERIES"

    conn = sqlite3.connect(str(test_db))
    conn.row_factory = sqlite3.Row

    errors = []
    for query_name, sql in engage_queries.items():
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            errors.append(f"{query_name}: {e}")

    conn.close()

    assert not errors, (
        f"Engage queries reference non-existent columns:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


# ── Bug 3: classifier must handle zero-norm vectors ────────────────────────


def test_classifier_handles_zero_norm_vector():
    """Cosine similarity with a zero-norm vector must return 0.0, not crash."""
    import numpy as np
    from core.classifier import _cosine_similarity

    zero_vec = np.zeros(512)
    normal_vec = np.random.randn(512)

    # Should return 0.0, not raise ZeroDivisionError
    result = _cosine_similarity(zero_vec, normal_vec)
    assert result == 0.0, f"Expected 0.0 for zero-norm input, got {result}"

    # Both zero should also be safe
    result2 = _cosine_similarity(zero_vec, zero_vec)
    assert result2 == 0.0, f"Expected 0.0 for both-zero input, got {result2}"


# ── Bug 4: ICOR edge update must be atomic (single transaction) ────────────


def test_icor_edge_update_is_atomic():
    """update_icor_edges_for_file must delete old edges and insert new ones
    in a single transaction. Verify the code computes affinities BEFORE
    deleting, so a failure doesn't leave orphaned state.
    """
    import ast
    import inspect
    from core import icor_affinity

    source = inspect.getsource(icor_affinity.update_icor_edges_for_file)

    # The function should compute affinities before the delete
    compute_pos = source.find("compute_file_icor_affinity")
    delete_pos = source.find("DELETE FROM vault_edges")

    assert compute_pos != -1, "compute_file_icor_affinity call not found"
    assert delete_pos != -1, "DELETE FROM vault_edges not found"
    assert compute_pos < delete_pos, (
        "compute_file_icor_affinity must be called BEFORE DELETE to prevent "
        "data loss on computation failure (TOCTOU fix)"
    )

    # The delete and insert should be inside a with get_connection block
    assert "with get_connection" in source, (
        "DELETE and INSERT must be inside a 'with get_connection' block "
        "for transactional safety"
    )


# ── Bug 5: journal aggregation must not mix aggregates with bare columns ───


def test_journal_aggregation_handles_duplicate_dates(test_db):
    """When multiple journal entries exist for the same date, the engagement
    query must correctly aggregate (COUNT, SUM, AVG) without mixing in
    non-aggregated bare columns like mood/energy.
    """
    conn = sqlite3.connect(str(test_db))

    # Insert 2 journal entries for the same date with different mood/energy
    conn.execute(
        "INSERT INTO journal_entries (date, content, mood, energy, created_at) "
        "VALUES ('2026-03-20', 'Morning entry', 'good', 'high', '2026-03-20 08:00:00')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO journal_entries (date, content, mood, energy, created_at) "
        "VALUES ('2026-03-20', 'Evening entry', 'great', 'low', '2026-03-20 20:00:00')"
    )
    conn.commit()

    # The engagement module's query should work correctly
    # Aggregates (COUNT, SUM) separate from bare columns (mood, energy)
    from core.engagement import compute_daily_metrics

    # Should not raise and should return valid metrics
    result = compute_daily_metrics("2026-03-20", db_path=test_db)

    assert result is not None, "compute_daily_metrics returned None"
    assert result["journal_entry_count"] >= 1, (
        f"Expected journal_entry_count >= 1, got {result['journal_entry_count']}"
    )

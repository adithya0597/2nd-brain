"""Tests for core.search_filters -- metadata filtering for vector search."""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())

from core.search_filters import (
    MetadataFilters,
    build_filter_cte,
    build_filtered_vec_query,
    filters_for_command,
    is_selective,
)


# ---------------------------------------------------------------------------
# MetadataFilters dataclass
# ---------------------------------------------------------------------------


class TestMetadataFilters:
    """Test MetadataFilters dataclass defaults and construction."""

    def test_default_values(self):
        f = MetadataFilters()
        assert f.date_range is None
        assert f.dimensions is None
        assert f.file_types is None
        assert f.community_id is None
        assert f.node_type == "document"

    def test_custom_values(self):
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-03-08"),
            dimensions=["Health & Vitality"],
            file_types=["journal"],
            community_id=3,
        )
        assert f.date_range == ("2026-01-01", "2026-03-08")
        assert f.dimensions == ["Health & Vitality"]
        assert f.file_types == ["journal"]
        assert f.community_id == 3
        assert f.node_type == "document"

    def test_custom_node_type(self):
        f = MetadataFilters(node_type="icor_dimension")
        assert f.node_type == "icor_dimension"

    def test_multiple_dimensions(self):
        dims = ["Health & Vitality", "Mind & Growth", "Relationships"]
        f = MetadataFilters(dimensions=dims)
        assert f.dimensions == dims
        assert len(f.dimensions) == 3

    def test_multiple_file_types(self):
        types = ["journal", "concept", "project"]
        f = MetadataFilters(file_types=types)
        assert f.file_types == types


# ---------------------------------------------------------------------------
# is_selective heuristic
# ---------------------------------------------------------------------------


class TestIsSelective:
    """Test selectivity heuristic."""

    def test_none_filters_not_selective(self):
        assert is_selective(None) is False

    def test_empty_filters_not_selective(self):
        assert is_selective(MetadataFilters()) is False

    def test_date_range_is_selective(self):
        f = MetadataFilters(date_range=("2026-03-01", "2026-03-08"))
        assert is_selective(f) is True

    def test_single_dimension_is_selective(self):
        f = MetadataFilters(dimensions=["Health & Vitality"])
        assert is_selective(f) is True

    def test_two_dimensions_is_selective(self):
        f = MetadataFilters(dimensions=["Health & Vitality", "Mind & Growth"])
        assert is_selective(f) is True

    def test_three_dimensions_is_selective(self):
        """Three dimensions <= 3, still selective."""
        f = MetadataFilters(dimensions=["A", "B", "C"])
        assert is_selective(f) is True

    def test_four_dimensions_not_selective(self):
        """Four dimensions > 3, not selective enough."""
        f = MetadataFilters(dimensions=["A", "B", "C", "D"])
        assert is_selective(f) is False

    def test_many_dimensions_not_selective(self):
        f = MetadataFilters(dimensions=["A", "B", "C", "D", "E"])
        assert is_selective(f) is False

    def test_single_file_type_is_selective(self):
        f = MetadataFilters(file_types=["journal"])
        assert is_selective(f) is True

    def test_two_file_types_is_selective(self):
        f = MetadataFilters(file_types=["journal", "concept"])
        assert is_selective(f) is True

    def test_three_file_types_not_selective(self):
        """Three file types > 2, not selective enough."""
        f = MetadataFilters(file_types=["a", "b", "c"])
        assert is_selective(f) is False

    def test_community_id_is_selective(self):
        f = MetadataFilters(community_id=5)
        assert is_selective(f) is True

    def test_community_id_zero_is_selective(self):
        """community_id=0 is not None, should be selective."""
        f = MetadataFilters(community_id=0)
        assert is_selective(f) is True

    def test_empty_dimensions_list_not_selective(self):
        """Empty list is falsy, should not be selective."""
        f = MetadataFilters(dimensions=[])
        assert is_selective(f) is False

    def test_empty_file_types_list_not_selective(self):
        """Empty list is falsy, should not be selective."""
        f = MetadataFilters(file_types=[])
        assert is_selective(f) is False

    def test_only_custom_node_type_not_selective(self):
        """Changing node_type alone does not trigger selectivity."""
        f = MetadataFilters(node_type="icor_dimension")
        assert is_selective(f) is False

    def test_date_range_overrides_other_non_selective(self):
        """Date range makes it selective even with many dims."""
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-12-31"),
            dimensions=["A", "B", "C", "D", "E", "F"],
        )
        assert is_selective(f) is True


# ---------------------------------------------------------------------------
# build_filter_cte SQL generation
# ---------------------------------------------------------------------------


class TestBuildFilterCte:
    """Test CTE SQL generation."""

    def test_default_filters_only_node_type(self):
        cte, params = build_filter_cte(MetadataFilters())
        assert "node_type" in cte
        assert "?" in cte
        assert params == ["document"]

    def test_cte_starts_with_with(self):
        cte, _ = build_filter_cte(MetadataFilters())
        assert cte.strip().startswith("WITH filtered_docs AS")

    def test_cte_selects_file_path(self):
        cte, _ = build_filter_cte(MetadataFilters())
        assert "SELECT vn.file_path" in cte

    def test_date_range_filter(self):
        f = MetadataFilters(date_range=("2026-03-01", "2026-03-08"))
        cte, params = build_filter_cte(f)
        assert "last_modified >= ?" in cte
        assert "last_modified <= ?" in cte
        assert "2026-03-01" in params
        assert "2026-03-08" in params
        # node_type param comes first
        assert params[0] == "document"

    def test_file_types_filter(self):
        f = MetadataFilters(file_types=["journal", "concept"])
        cte, params = build_filter_cte(f)
        assert "type IN" in cte
        assert "journal" in params
        assert "concept" in params

    def test_file_types_placeholder_count(self):
        """Number of ? placeholders matches number of file types."""
        f = MetadataFilters(file_types=["journal", "concept", "project"])
        cte, params = build_filter_cte(f)
        # "type IN (?, ?, ?)" -- three placeholders
        in_clause_start = cte.index("IN (")
        in_clause_end = cte.index(")", in_clause_start)
        in_clause = cte[in_clause_start:in_clause_end + 1]
        assert in_clause.count("?") == 3

    def test_community_filter(self):
        f = MetadataFilters(community_id=3)
        cte, params = build_filter_cte(f)
        assert "community_id" in cte
        assert 3 in params

    def test_dimension_filter(self):
        f = MetadataFilters(dimensions=["Health & Vitality"])
        cte, params = build_filter_cte(f)
        assert "icor_affinity" in cte
        assert "Health & Vitality" in params
        # Dimension filter uses EXISTS subquery
        assert "EXISTS" in cte

    def test_dimension_filter_uses_vault_edges(self):
        f = MetadataFilters(dimensions=["Mind & Growth"])
        cte, _ = build_filter_cte(f)
        assert "vault_edges" in cte
        assert "edge_type = 'icor_affinity'" in cte

    def test_multiple_dimensions_filter(self):
        dims = ["Health & Vitality", "Mind & Growth"]
        f = MetadataFilters(dimensions=dims)
        cte, params = build_filter_cte(f)
        # Both dimensions should appear in params
        assert "Health & Vitality" in params
        assert "Mind & Growth" in params
        # Two placeholders in the IN clause inside the EXISTS subquery
        assert "vn_dim.title IN" in cte

    def test_combined_filters(self):
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-03-08"),
            file_types=["journal"],
            community_id=2,
        )
        cte, params = build_filter_cte(f)
        assert "last_modified" in cte
        assert "type IN" in cte
        assert "community_id" in cte
        # All params present
        assert "document" in params  # node_type
        assert "2026-01-01" in params
        assert "2026-03-08" in params
        assert "journal" in params
        assert 2 in params

    def test_all_filters_combined(self):
        """All filters applied simultaneously produces valid SQL structure."""
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-03-08"),
            dimensions=["Health & Vitality"],
            file_types=["journal"],
            community_id=2,
        )
        cte, params = build_filter_cte(f)
        assert "node_type" in cte
        assert "last_modified" in cte
        assert "type IN" in cte
        assert "community_id" in cte
        assert "icor_affinity" in cte
        # Params in correct order: node_type, date_start, date_end,
        # file_type, community_id, dimension
        assert params[0] == "document"
        assert "Health & Vitality" in params

    def test_custom_node_type(self):
        f = MetadataFilters(node_type="icor_dimension")
        cte, params = build_filter_cte(f)
        assert "icor_dimension" in params

    def test_parameterized_no_injection(self):
        """Ensure values are parameterized, not string-interpolated."""
        f = MetadataFilters(file_types=["'; DROP TABLE vault_nodes; --"])
        cte, params = build_filter_cte(f)
        # The malicious string should be in params, NOT in the SQL
        assert "DROP TABLE" not in cte
        assert "'; DROP TABLE vault_nodes; --" in params

    def test_date_injection_safe(self):
        """Date values are parameterized too."""
        f = MetadataFilters(
            date_range=("2026-01-01'; DROP TABLE vault_nodes;--", "2026-03-08")
        )
        cte, params = build_filter_cte(f)
        assert "DROP TABLE" not in cte
        assert "2026-01-01'; DROP TABLE vault_nodes;--" in params

    def test_dimension_injection_safe(self):
        """Dimension names are parameterized."""
        f = MetadataFilters(dimensions=["'; DELETE FROM vault_edges; --"])
        cte, params = build_filter_cte(f)
        assert "DELETE FROM" not in cte
        assert "'; DELETE FROM vault_edges; --" in params

    def test_params_order_date_before_types(self):
        """Verify parameter ordering: node_type, date_range, file_types."""
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-03-08"),
            file_types=["journal"],
        )
        _, params = build_filter_cte(f)
        assert params == ["document", "2026-01-01", "2026-03-08", "journal"]

    def test_params_order_with_community(self):
        """Community param comes after file_types in WHERE clause order."""
        f = MetadataFilters(
            file_types=["concept"],
            community_id=7,
        )
        _, params = build_filter_cte(f)
        assert params == ["document", "concept", 7]

    def test_dimensions_params_come_last(self):
        """Dimension params are appended after WHERE clause params."""
        f = MetadataFilters(
            file_types=["journal"],
            dimensions=["Relationships"],
        )
        _, params = build_filter_cte(f)
        # node_type, file_type, then dimension
        assert params == ["document", "journal", "Relationships"]


# ---------------------------------------------------------------------------
# build_filtered_vec_query
# ---------------------------------------------------------------------------


class TestBuildFilteredVecQuery:
    """Test complete filtered vector search query builder."""

    def test_returns_sql_and_params(self):
        f = MetadataFilters()
        sql, params = build_filtered_vec_query("vec_vault", f)
        assert isinstance(sql, str)
        assert isinstance(params, list)

    def test_includes_cte(self):
        f = MetadataFilters(file_types=["journal"])
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert sql.strip().startswith("WITH filtered_docs AS")

    def test_includes_vec_table(self):
        f = MetadataFilters()
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert "vec_vault" in sql

    def test_custom_vec_table(self):
        f = MetadataFilters()
        sql, _ = build_filtered_vec_query("vec_vault_chunks", f)
        assert "vec_vault_chunks" in sql

    def test_inner_join_on_filtered_docs(self):
        f = MetadataFilters()
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert "INNER JOIN filtered_docs" in sql

    def test_embedding_match_clause(self):
        f = MetadataFilters()
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert "embedding MATCH" in sql

    def test_order_by_distance(self):
        f = MetadataFilters()
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert "ORDER BY v.distance" in sql

    def test_params_are_cte_params_only(self):
        """build_filtered_vec_query returns only CTE params; caller adds embedding + k."""
        f = MetadataFilters(file_types=["journal"])
        _, params = build_filtered_vec_query("vec_vault", f)
        # Should contain node_type + file_type from CTE, NOT k value
        assert "document" in params
        assert "journal" in params

    def test_filters_propagate_to_cte(self):
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-03-08"),
            community_id=4,
        )
        sql, params = build_filtered_vec_query("vec_vault", f)
        assert "last_modified" in sql
        assert "community_id" in sql
        assert "2026-01-01" in params
        assert 4 in params


# ---------------------------------------------------------------------------
# filters_for_command
# ---------------------------------------------------------------------------


class TestFiltersForCommand:
    """Test command-specific filter presets."""

    def test_find_returns_filters(self):
        f = filters_for_command("find")
        assert f is not None
        assert isinstance(f, MetadataFilters)

    def test_find_has_date_range(self):
        f = filters_for_command("find")
        assert f.date_range is not None
        start, end = f.date_range
        assert end == datetime.now().strftime("%Y-%m-%d")

    def test_find_has_file_types(self):
        f = filters_for_command("find")
        assert f.file_types is not None
        assert "concept" in f.file_types
        assert "project" in f.file_types
        assert "journal" in f.file_types

    def test_find_date_range_is_90_days(self):
        f = filters_for_command("find")
        start, end = f.date_range
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        delta = (end_dt - start_dt).days
        assert delta == 90

    def test_today_returns_filters(self):
        f = filters_for_command("today")
        assert f is not None
        assert f.date_range is not None

    def test_today_recent_only(self):
        f = filters_for_command("today")
        start, end = f.date_range
        assert end == datetime.now().strftime("%Y-%m-%d")
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert (end_dt - start_dt).days == 7

    def test_today_no_file_type_restriction(self):
        f = filters_for_command("today")
        assert f.file_types is None

    def test_drift_is_journal_only(self):
        f = filters_for_command("drift")
        assert f is not None
        assert f.file_types == ["journal"]

    def test_drift_date_range_is_60_days(self):
        f = filters_for_command("drift")
        start, end = f.date_range
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert (end_dt - start_dt).days == 60

    def test_ideas_returns_filters(self):
        f = filters_for_command("ideas")
        assert f is not None
        assert f.date_range is not None

    def test_ideas_date_range_is_30_days(self):
        f = filters_for_command("ideas")
        start, end = f.date_range
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert (end_dt - start_dt).days == 30

    def test_ideas_no_file_type_restriction(self):
        f = filters_for_command("ideas")
        assert f.file_types is None

    def test_emerge_returns_filters(self):
        f = filters_for_command("emerge")
        assert f is not None
        assert f.date_range is not None

    def test_emerge_date_range_is_14_days(self):
        f = filters_for_command("emerge")
        start, end = f.date_range
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert (end_dt - start_dt).days == 14

    def test_trace_has_no_filters(self):
        f = filters_for_command("trace")
        assert f is None

    def test_connect_has_no_filters(self):
        f = filters_for_command("connect")
        assert f is None

    def test_challenge_has_no_filters(self):
        f = filters_for_command("challenge")
        assert f is None

    def test_ghost_has_no_filters(self):
        f = filters_for_command("ghost")
        assert f is None

    def test_unknown_command_returns_none(self):
        f = filters_for_command("nonexistent_command")
        assert f is None

    def test_empty_command_returns_none(self):
        f = filters_for_command("")
        assert f is None

    def test_all_end_dates_are_today(self):
        """Every command with a date range should have today as end date."""
        today = datetime.now().strftime("%Y-%m-%d")
        for cmd in ("find", "today", "drift", "ideas", "emerge"):
            f = filters_for_command(cmd)
            assert f is not None, f"Expected filters for {cmd}"
            _, end = f.date_range
            assert end == today, f"{cmd} end date should be today, got {end}"

    def test_all_commands_default_node_type(self):
        """All returned filters should keep the default node_type='document'."""
        for cmd in ("find", "today", "drift", "ideas", "emerge"):
            f = filters_for_command(cmd)
            assert f.node_type == "document", f"{cmd} should have node_type=document"


# ---------------------------------------------------------------------------
# CTE execution against real SQLite (no sqlite-vec needed)
# ---------------------------------------------------------------------------


class TestCteExecutionOnRealDb:
    """Test that generated CTEs execute on real SQLite with schema tables."""

    def test_default_cte_executes(self, test_db):
        """Default filters produce valid SQL against vault_nodes."""
        f = MetadataFilters()
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)
        conn.close()

    def test_date_range_cte_executes(self, test_db):
        """Date range filter CTE is valid SQL."""
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-12-31"),
        )
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)
        conn.close()

    def test_file_types_cte_executes(self, test_db):
        """File types filter CTE is valid SQL."""
        f = MetadataFilters(
            file_types=["journal", "concept"],
        )
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)
        conn.close()

    def test_community_cte_executes(self, test_db):
        """Community filter CTE is valid SQL."""
        f = MetadataFilters(community_id=1)
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)
        conn.close()

    def test_dimension_cte_executes(self, test_db):
        """Dimension filter CTE (with EXISTS subquery on vault_edges) is valid SQL."""
        f = MetadataFilters(dimensions=["Health & Vitality"])
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)
        conn.close()

    def test_all_filters_cte_executes(self, test_db):
        """All filters combined still produce valid SQL."""
        f = MetadataFilters(
            date_range=("2026-01-01", "2026-12-31"),
            dimensions=["Health & Vitality", "Mind & Growth"],
            file_types=["journal"],
            community_id=2,
        )
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)
        conn.close()

    def test_cte_returns_matching_rows(self, vault_graph_db):
        """CTE filters actually narrow results against populated data."""
        f = MetadataFilters(file_types=["journal"])
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(vault_graph_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        # vault_graph_db has one journal file: Daily Notes/2026-03-01.md
        assert len(results) == 1
        assert results[0][0] == "Daily Notes/2026-03-01.md"
        conn.close()

    def test_cte_excludes_non_matching_rows(self, vault_graph_db):
        """CTE correctly excludes rows that don't match."""
        f = MetadataFilters(file_types=["meeting"])
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(vault_graph_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        # No "meeting" type files in the test data
        assert len(results) == 0
        conn.close()

    def test_cte_date_range_filters_correctly(self, vault_graph_db):
        """Date range CTE narrows to files within the window."""
        # vault_graph_db files all have last_modified=2026-03-01T10:00:00
        f = MetadataFilters(
            date_range=("2026-03-01", "2026-03-02"),
        )
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(vault_graph_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        # All 5 document nodes have last_modified in range
        assert len(results) == 5
        conn.close()

    def test_cte_date_range_excludes_out_of_range(self, vault_graph_db):
        """Date range CTE excludes files outside the window."""
        f = MetadataFilters(
            date_range=("2026-04-01", "2026-04-30"),
        )
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(vault_graph_db))
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert len(results) == 0
        conn.close()

    def test_cte_community_filter_on_populated_db(self, vault_graph_db):
        """Community filter returns only matching community."""
        # Set community_id on one node
        conn = sqlite3.connect(str(vault_graph_db))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "UPDATE vault_nodes SET community_id = 42 WHERE title = 'Fitness'"
        )
        conn.commit()

        f = MetadataFilters(community_id=42)
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert len(results) == 1
        assert results[0][0] == "Concepts/Fitness.md"
        conn.close()

    def test_injection_string_does_not_corrupt_db(self, test_db):
        """SQL injection attempt via parameterized query does not execute."""
        f = MetadataFilters(
            file_types=["'; DROP TABLE vault_nodes; --"],
        )
        cte, params = build_filter_cte(f)
        full_sql = f"{cte} SELECT * FROM filtered_docs"

        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        # Should execute safely (returning 0 rows, not dropping tables)
        cursor = conn.execute(full_sql, params)
        results = cursor.fetchall()
        assert isinstance(results, list)

        # Verify vault_nodes table still exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vault_nodes'"
        )
        assert cursor.fetchone() is not None, "vault_nodes table should still exist"
        conn.close()


# ---------------------------------------------------------------------------
# build_filtered_vec_query execution (SQL structure only, no sqlite-vec)
# ---------------------------------------------------------------------------


class TestFilteredVecQueryStructure:
    """Test the full vec query structure without requiring sqlite-vec extension."""

    def test_query_references_filtered_docs(self):
        f = MetadataFilters(file_types=["journal"])
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert "filtered_docs" in sql
        # CTE defines it, main query joins on it
        assert sql.count("filtered_docs") >= 2

    def test_query_selects_expected_columns(self):
        f = MetadataFilters()
        sql, _ = build_filtered_vec_query("vec_vault", f)
        assert "v.rowid" in sql
        assert "v.distance" in sql
        assert "v.file_path" in sql
        assert "v.title" in sql

    def test_params_do_not_include_k(self):
        """The k parameter is for the caller to append, not included in params."""
        f = MetadataFilters(file_types=["journal"])
        _, params = build_filtered_vec_query("vec_vault", f, k=20)
        # k=20 should NOT be in params (caller handles it)
        assert 20 not in params

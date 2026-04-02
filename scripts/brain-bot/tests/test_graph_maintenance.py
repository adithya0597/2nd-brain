"""Tests for graph maintenance module."""
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


class TestFindOrphanDocuments:
    """Tests for find_orphan_documents()."""

    def test_finds_orphan_with_no_edges(self, test_db):
        """An isolated document node should be returned as an orphan."""
        conn = sqlite3.connect(str(test_db))
        conn.execute("PRAGMA foreign_keys=ON")
        # Insert a document with no edges at all
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type, last_modified) "
            "VALUES ('Inbox/orphan.md', 'orphan', 'note', 'document', '2026-03-01')"
        )
        conn.commit()
        conn.close()

        from core.graph_maintenance import find_orphan_documents
        orphans = find_orphan_documents(db_path=test_db)
        titles = [o["title"] for o in orphans]
        assert "orphan" in titles

    def test_connected_nodes_not_orphans(self, vault_graph_db):
        """Nodes with wikilink edges should not appear as orphans."""
        from core.graph_maintenance import find_orphan_documents
        orphans = find_orphan_documents(db_path=vault_graph_db)
        # Nodes 1-3 are connected via wikilinks, should not be orphans
        titles = [o["title"] for o in orphans]
        assert "2026-03-01" not in titles
        assert "Fitness" not in titles
        assert "Nutrition" not in titles

    def test_empty_graph_returns_empty(self, test_db):
        """An empty vault_nodes table returns an empty list."""
        from core.graph_maintenance import find_orphan_documents
        orphans = find_orphan_documents(db_path=test_db)
        assert orphans == []


class TestSuggestConnections:
    """Tests for suggest_connections_for_orphan()."""

    @patch("core.embedding_store.search_similar")
    def test_returns_top_k(self, mock_search, test_db):
        """Should return up to top_k suggestions from embedding search."""
        mock_search.return_value = [
            {"file_path": "Concepts/A.md", "title": "A", "distance": 0.2},
            {"file_path": "Concepts/B.md", "title": "B", "distance": 0.3},
            {"file_path": "Concepts/C.md", "title": "C", "distance": 0.5},
        ]
        from core.graph_maintenance import suggest_connections_for_orphan
        suggestions = suggest_connections_for_orphan("orphan", top_k=3, db_path=test_db)
        assert len(suggestions) == 3
        assert suggestions[0]["title"] == "A"
        assert suggestions[0]["similarity_score"] == 0.98  # 1.0 - 0.2²/2

    @patch("core.embedding_store.search_similar")
    def test_excludes_self(self, mock_search, test_db):
        """Should exclude the orphan itself from results."""
        mock_search.return_value = [
            {"file_path": "Inbox/orphan.md", "title": "orphan", "distance": 0.0},
            {"file_path": "Concepts/A.md", "title": "A", "distance": 0.3},
        ]
        from core.graph_maintenance import suggest_connections_for_orphan
        suggestions = suggest_connections_for_orphan("orphan", top_k=3, db_path=test_db)
        titles = [s["title"] for s in suggestions]
        assert "orphan" not in titles
        assert "A" in titles

    @patch("core.embedding_store.search_similar", side_effect=Exception("No model"))
    def test_graceful_when_no_embeddings(self, mock_search, test_db):
        """Should return empty list when embedding search fails."""
        from core.graph_maintenance import suggest_connections_for_orphan
        suggestions = suggest_connections_for_orphan("orphan", top_k=3, db_path=test_db)
        assert suggestions == []


class TestFindStaleConcepts:
    """Tests for find_stale_concepts()."""

    def test_finds_old_concepts(self, test_db):
        """Documents older than the threshold should be returned."""
        conn = sqlite3.connect(str(test_db))
        old_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type, last_modified) "
            "VALUES ('Concepts/Old.md', 'Old', 'concept', 'document', ?)",
            (old_date,),
        )
        conn.commit()
        conn.close()

        from core.graph_maintenance import find_stale_concepts
        stale = find_stale_concepts(days=60, db_path=test_db)
        titles = [s["title"] for s in stale]
        assert "Old" in titles
        assert stale[0]["days_stale"] >= 60

    def test_recent_not_stale(self, test_db):
        """Recently modified documents should not be considered stale."""
        conn = sqlite3.connect(str(test_db))
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type, last_modified) "
            "VALUES ('Concepts/Fresh.md', 'Fresh', 'concept', 'document', ?)",
            (today,),
        )
        conn.commit()
        conn.close()

        from core.graph_maintenance import find_stale_concepts
        stale = find_stale_concepts(days=60, db_path=test_db)
        titles = [s["title"] for s in stale]
        assert "Fresh" not in titles

    def test_custom_days_threshold(self, test_db):
        """Custom day threshold should be respected."""
        conn = sqlite3.connect(str(test_db))
        date_45_ago = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type, last_modified) "
            "VALUES ('Concepts/Medium.md', 'Medium', 'concept', 'document', ?)",
            (date_45_ago,),
        )
        conn.commit()
        conn.close()

        from core.graph_maintenance import find_stale_concepts
        # Should be found with 30-day threshold
        stale_30 = find_stale_concepts(days=30, db_path=test_db)
        titles_30 = [s["title"] for s in stale_30]
        assert "Medium" in titles_30

        # Should NOT be found with 60-day threshold
        stale_60 = find_stale_concepts(days=60, db_path=test_db)
        titles_60 = [s["title"] for s in stale_60]
        assert "Medium" not in titles_60


class TestComputeGraphDensity:
    """Tests for compute_graph_density()."""

    def test_known_graph_density(self, vault_graph_db):
        """Density should match hand-calculated value for the test graph."""
        from core.graph_maintenance import compute_graph_density
        result = compute_graph_density(db_path=vault_graph_db)
        # vault_graph_db has 5 document nodes and 4 wikilink edges
        assert result["node_count"] == 5
        assert result["edge_count"] == 4
        # density = 2 * 4 / (5 * 4) = 0.4
        assert abs(result["density"] - 0.4) < 0.001
        assert result["target_density"] == 0.05

    def test_empty_graph_zero(self, test_db):
        """Empty graph should have density 0."""
        from core.graph_maintenance import compute_graph_density
        result = compute_graph_density(db_path=test_db)
        assert result["node_count"] == 0
        assert result["edge_count"] == 0
        assert result["density"] == 0.0

    def test_single_node_no_division_error(self, test_db):
        """A single node should not cause division by zero."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type, last_modified) "
            "VALUES ('solo.md', 'Solo', 'note', 'document', '2026-03-01')"
        )
        conn.commit()
        conn.close()

        from core.graph_maintenance import compute_graph_density
        result = compute_graph_density(db_path=test_db)
        assert result["node_count"] == 1
        assert result["density"] == 0.0  # No division error


class TestRunMaintenance:
    """Tests for run_maintenance() orchestrator."""

    @patch("core.graph_maintenance.suggest_connections_for_orphan")
    def test_returns_all_sections(self, mock_suggest, vault_graph_db):
        """run_maintenance should return orphans, stale_concepts, density, timestamp."""
        mock_suggest.return_value = [
            {"file_path": "Concepts/A.md", "title": "A", "similarity_score": 0.8}
        ]
        from core.graph_maintenance import run_maintenance
        result = run_maintenance(db_path=vault_graph_db)
        assert "orphans" in result
        assert "stale_concepts" in result
        assert "density" in result
        assert "timestamp" in result
        assert "total_orphans" in result

    @patch("core.graph_maintenance.suggest_connections_for_orphan")
    def test_orphans_have_suggestions(self, mock_suggest, test_db):
        """Each orphan in the result should have a suggestions key."""
        mock_suggest.return_value = [
            {"file_path": "Concepts/B.md", "title": "B", "similarity_score": 0.7}
        ]
        # Insert an orphan
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type, node_type, last_modified) "
            "VALUES ('orphan.md', 'orphan', 'note', 'document', '2026-03-01')"
        )
        conn.commit()
        conn.close()

        from core.graph_maintenance import run_maintenance
        result = run_maintenance(db_path=test_db)
        assert len(result["orphans"]) >= 1
        for orphan in result["orphans"]:
            assert "suggestions" in orphan


@pytest.mark.skip(reason="format_maintenance_report not yet implemented in formatter.py")
class TestFormatMaintenanceReport:
    """Tests for format_maintenance_report() in formatter.py."""

    def test_format_with_orphans(self):
        """Report should include orphan section with suggestions."""
        from core.formatter import format_maintenance_report
        data = {
            "density": {"node_count": 50, "edge_count": 30, "density": 0.024, "target_density": 0.05},
            "orphans": [
                {
                    "title": "meeting-notes-march-5",
                    "file_path": "Inbox/meeting.md",
                    "suggestions": [
                        {"title": "project-planning-review", "similarity_score": 0.82, "file_path": "Projects/review.md"}
                    ],
                }
            ],
            "stale_concepts": [],
            "total_orphans": 1,
            "timestamp": "2026-03-17T15:00:00",
        }
        text, keyboard = format_maintenance_report(data)
        assert "meeting-notes-march-5" in text
        assert "project-planning-review" in text
        assert "0.82" in text
        assert keyboard is None

    def test_format_empty(self):
        """Report with no orphans or stale should show healthy messages."""
        from core.formatter import format_maintenance_report
        data = {
            "density": {"node_count": 100, "edge_count": 250, "density": 0.05, "target_density": 0.05},
            "orphans": [],
            "stale_concepts": [],
            "total_orphans": 0,
            "timestamp": "2026-03-17T15:00:00",
        }
        text, keyboard = format_maintenance_report(data)
        assert "No orphan documents" in text
        assert "No stale concepts" in text
        assert "healthy" in text.lower()

    def test_density_displayed(self):
        """Graph density should be displayed with node and edge counts."""
        from core.formatter import format_maintenance_report
        data = {
            "density": {"node_count": 200, "edge_count": 400, "density": 0.02, "target_density": 0.05},
            "orphans": [],
            "stale_concepts": [],
            "total_orphans": 0,
            "timestamp": "2026-03-17T15:00:00",
        }
        text, _ = format_maintenance_report(data)
        assert "200" in text
        assert "400" in text
        assert "0.0200" in text
        assert "40%" in text  # 0.02 / 0.05 = 40%

    def test_stale_displayed(self):
        """Stale concepts should be listed with days count."""
        from core.formatter import format_maintenance_report
        data = {
            "density": {"node_count": 50, "edge_count": 30, "density": 0.024, "target_density": 0.05},
            "orphans": [],
            "stale_concepts": [
                {"title": "dormant-concept", "days_stale": 87, "file_path": "Concepts/dormant.md", "last_modified": "2025-12-21"}
            ],
            "total_orphans": 0,
            "timestamp": "2026-03-17T15:00:00",
        }
        text, _ = format_maintenance_report(data)
        assert "dormant-concept" in text
        assert "87" in text
        assert "Stale Concepts" in text

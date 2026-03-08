"""Tests for core.community — community detection and structural analysis."""
import contextlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path & module setup
# ---------------------------------------------------------------------------
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

sys.modules.setdefault("config", MagicMock())


# Provide a working get_connection
@contextlib.contextmanager
def _get_connection(db_path=None, row_factory=None):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    if row_factory:
        conn.row_factory = row_factory
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_db_mod = MagicMock()
_db_mod.get_connection = _get_connection
sys.modules.setdefault("core.db_connection", _db_mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    return c


def _setup_graph(db_path):
    """Create a test graph with two clear communities.

    Community A: nodes 1-3 (densely connected triangle)
    Community B: nodes 4-5 (connected to each other)
    Bridge: node 3 connects to node 4
    """
    conn = _conn(db_path)

    # Community A nodes
    conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('a1.md', 'A1', 'concept')")
    conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('a2.md', 'A2', 'concept')")
    conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('a3.md', 'A3', 'concept')")

    # Community B nodes
    conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('b1.md', 'B1', 'concept')")
    conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('b2.md', 'B2', 'concept')")

    # Community A edges (dense triangle — bidirectional)
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 2, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (2, 1, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 3, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (3, 1, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (2, 3, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (3, 2, 'wikilink')")

    # Community B edges (bidirectional)
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (4, 5, 'wikilink')")
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (5, 4, 'wikilink')")

    # Bridge: A3 -> B1
    conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (3, 4, 'wikilink')")

    conn.commit()
    conn.close()


def _setup_graph_with_icor(db_path):
    """Like _setup_graph but also adds ICOR nodes and affinity edges.

    Community A has ICOR connections, Community B does not.
    """
    _setup_graph(db_path)

    conn = _conn(db_path)
    # Add an ICOR dimension node (node 6)
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, type, node_type) "
        "VALUES ('icor://Health & Vitality', 'Health & Vitality', '', 'icor_dimension')"
    )
    # Connect community A node 1 to ICOR
    conn.execute(
        "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type, weight) "
        "VALUES (1, 6, 'icor_affinity', 0.45)"
    )
    conn.commit()
    conn.close()


# ===========================================================================
# Community Detection
# ===========================================================================


class TestDetectCommunities:
    """Test community detection with networkx."""

    def test_detect_communities_with_networkx(self, test_db):
        """Louvain should find two communities in our graph."""
        _setup_graph(test_db)

        from core import community

        if not community._NX_AVAILABLE:
            pytest.skip("networkx not installed")

        assignments = community.detect_communities(db_path=test_db)

        assert isinstance(assignments, dict)
        # Should have at least 2 distinct community IDs
        assert len(set(assignments.values())) >= 2
        # Nodes within the same dense cluster should share a community
        if 1 in assignments and 2 in assignments:
            assert assignments[1] == assignments[2]  # A1 and A2 in same community

    def test_detect_communities_graceful_degradation(self, test_db):
        """When _NX_AVAILABLE is False, returns empty dict."""
        _setup_graph(test_db)

        from core import community

        with patch.object(community, "_NX_AVAILABLE", False):
            assignments = community.detect_communities(db_path=test_db)

        assert assignments == {}

    def test_detect_communities_empty_graph(self, test_db):
        """Empty graph returns empty dict."""
        from core import community

        if not community._NX_AVAILABLE:
            pytest.skip("networkx not installed")

        assignments = community.detect_communities(db_path=test_db)
        assert assignments == {}


# ===========================================================================
# Community ID Updates
# ===========================================================================


class TestUpdateCommunityIds:
    """Test updating community_id column on vault_nodes."""

    def test_update_community_ids(self, test_db):
        """update_community_ids should run detection and persist results."""
        _setup_graph(test_db)

        from core import community

        if not community._NX_AVAILABLE:
            pytest.skip("networkx not installed")

        count = community.update_community_ids(db_path=test_db)

        assert count > 0

        conn = _conn(test_db)
        rows = conn.execute(
            "SELECT id, community_id FROM vault_nodes ORDER BY id"
        ).fetchall()
        conn.close()

        # At least some nodes should have community_id set
        assigned = [r for r in rows if r["community_id"] is not None]
        assert len(assigned) >= 2

    def test_update_community_ids_no_networkx(self, test_db):
        """Without networkx, returns 0 and doesn't crash."""
        _setup_graph(test_db)

        from core import community

        with patch.object(community, "_NX_AVAILABLE", False):
            count = community.update_community_ids(db_path=test_db)

        assert count == 0


# ===========================================================================
# Community Queries
# ===========================================================================


class TestGetCommunityMembers:
    """Test retrieving nodes by community_id."""

    def test_get_community_members(self, test_db):
        """Insert nodes with community_id, verify retrieval."""
        _setup_graph(test_db)

        # Set community IDs manually
        conn = _conn(test_db)
        conn.execute("UPDATE vault_nodes SET community_id=0 WHERE id IN (1, 2, 3)")
        conn.execute("UPDATE vault_nodes SET community_id=1 WHERE id IN (4, 5)")
        conn.commit()
        conn.close()

        from core import community

        members = community.get_community_members(community_id=0, db_path=test_db)

        assert len(members) == 3
        titles = {m["title"] for m in members}
        assert titles == {"A1", "A2", "A3"}

    def test_get_community_members_empty(self, test_db):
        """Nonexistent community returns empty list."""
        _setup_graph(test_db)

        from core import community

        members = community.get_community_members(community_id=999, db_path=test_db)

        assert members == []


# ===========================================================================
# Structural Analysis
# ===========================================================================


class TestGetStructuralGaps:
    """Test identifying communities without ICOR connections."""

    def test_get_structural_gaps(self, test_db):
        """Communities without ICOR affinity edges are structural gaps."""
        _setup_graph_with_icor(test_db)

        # Assign community IDs
        conn = _conn(test_db)
        conn.execute("UPDATE vault_nodes SET community_id=0 WHERE id IN (1, 2, 3)")
        conn.execute("UPDATE vault_nodes SET community_id=1 WHERE id IN (4, 5)")
        conn.commit()
        conn.close()

        from core import community

        gaps = community.get_structural_gaps(db_path=test_db)

        assert isinstance(gaps, list)
        gap_ids = {g["community_id"] for g in gaps}
        assert 1 in gap_ids  # Community B is a gap
        assert 0 not in gap_ids  # Community A is connected to ICOR


class TestGetBridgeNodes:
    """Test identifying bridge nodes that connect multiple communities."""

    def test_get_bridge_nodes(self, test_db):
        """Node 3 (A3) bridges community A and B."""
        _setup_graph(test_db)

        # Assign community IDs
        conn = _conn(test_db)
        conn.execute("UPDATE vault_nodes SET community_id=0 WHERE id IN (1, 2, 3)")
        conn.execute("UPDATE vault_nodes SET community_id=1 WHERE id IN (4, 5)")
        conn.commit()
        conn.close()

        from core import community

        # min_communities=1: node connects to at least 1 community different from its own
        bridges = community.get_bridge_nodes(min_communities=1, db_path=test_db)

        assert isinstance(bridges, list)
        bridge_ids = {b["id"] for b in bridges}
        # Node 3 (community 0) has edge to node 4 (community 1) -> bridge
        assert 3 in bridge_ids

    def test_get_bridge_nodes_no_bridges(self, test_db):
        """Graph with single community has no bridge nodes."""
        conn = _conn(test_db)
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('x.md', 'X', '')")
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('y.md', 'Y', '')")
        conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 2, 'wikilink')")
        conn.execute("UPDATE vault_nodes SET community_id=0")
        conn.commit()
        conn.close()

        from core import community

        bridges = community.get_bridge_nodes(db_path=test_db)

        assert bridges == []

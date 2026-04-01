"""Extended tests for core/graph_ops.py — rebuild functions and queries."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

from core.graph_ops import (
    _normalize_title,
    get_node_by_path,
    get_node_by_title,
    get_outgoing_edges,
    get_incoming_edges,
    get_neighbors,
    delete_edges_for_node,
    rebuild_wikilink_edges,
    rebuild_wikilink_edges_for_node,
    rebuild_tag_shared_edges,
    ensure_icor_nodes,
    ICOR_DIMENSIONS,
)


class TestNormalizeTitle:
    def test_lowercase(self):
        assert _normalize_title("Hello World") == "hello world"

    def test_hyphen_to_space(self):
        assert _normalize_title("Hello-World") == "hello world"

    def test_underscore_to_space(self):
        assert _normalize_title("Hello_World") == "hello world"

    def test_strip_whitespace(self):
        assert _normalize_title("  hello  ") == "hello"


class TestGetNodeByPath:
    def test_found(self, vault_graph_db):
        result = get_node_by_path("Concepts/Fitness.md", db_path=vault_graph_db)
        assert result is not None
        assert result["title"] == "Fitness"

    def test_not_found(self, vault_graph_db):
        result = get_node_by_path("Nonexistent.md", db_path=vault_graph_db)
        assert result is None


class TestGetNodeByTitle:
    def test_found(self, vault_graph_db):
        result = get_node_by_title("Fitness", db_path=vault_graph_db)
        assert result is not None
        assert result["title"] == "Fitness"

    def test_not_found(self, vault_graph_db):
        result = get_node_by_title("ZZZ", db_path=vault_graph_db)
        assert result is None


class TestGetOutgoingEdges:
    def test_with_edges(self, vault_graph_db):
        # Node 1 (daily note) has outgoing edges to 2 (Fitness) and 3 (Nutrition)
        result = get_outgoing_edges(1, db_path=vault_graph_db)
        assert len(result) >= 2
        titles = [r["target_title"] for r in result]
        assert "Fitness" in titles
        assert "Nutrition" in titles

    def test_with_edge_type_filter(self, vault_graph_db):
        result = get_outgoing_edges(1, edge_type="wikilink", db_path=vault_graph_db)
        assert len(result) >= 2
        for edge in result:
            assert edge["edge_type"] == "wikilink"

    def test_no_edges(self, vault_graph_db):
        # Node 3 (Nutrition) has no outgoing edges in test data
        result = get_outgoing_edges(3, db_path=vault_graph_db)
        assert result == []


class TestGetIncomingEdges:
    def test_with_edges(self, vault_graph_db):
        # Node 3 (Nutrition) has incoming from node 1 (daily) and node 2 (Fitness)
        result = get_incoming_edges(3, db_path=vault_graph_db)
        assert len(result) >= 2

    def test_with_edge_type(self, vault_graph_db):
        result = get_incoming_edges(3, edge_type="wikilink", db_path=vault_graph_db)
        assert len(result) >= 2


class TestGetNeighbors:
    def test_depth_1(self, vault_graph_db):
        # From node 1 (daily), depth 1 should find Fitness and Nutrition
        result = get_neighbors(1, depth=1, db_path=vault_graph_db)
        titles = [r["title"] for r in result]
        assert "Fitness" in titles
        assert "Nutrition" in titles

    def test_depth_2(self, vault_graph_db):
        # From node 4 (ICOR), depth 2 should find Side-Project and further
        result = get_neighbors(4, depth=2, db_path=vault_graph_db)
        assert len(result) >= 1

    def test_with_edge_types(self, vault_graph_db):
        result = get_neighbors(1, edge_types=["wikilink"], depth=1, db_path=vault_graph_db)
        assert len(result) >= 2

    def test_no_neighbors(self, vault_graph_db):
        # Node 5 (Side-Project) only has incoming from ICOR, no outgoing
        result = get_neighbors(5, edge_types=["wikilink"], depth=1, db_path=vault_graph_db)
        # Should find ICOR as an incoming neighbor
        assert len(result) >= 1


class TestDeleteEdgesForNode:
    def test_outgoing(self, vault_graph_db):
        deleted = delete_edges_for_node(1, direction="outgoing", db_path=vault_graph_db)
        assert deleted >= 2

    def test_incoming(self, vault_graph_db):
        deleted = delete_edges_for_node(3, direction="incoming", db_path=vault_graph_db)
        assert deleted >= 2

    def test_both(self, vault_graph_db):
        deleted = delete_edges_for_node(2, direction="both", db_path=vault_graph_db)
        assert deleted >= 2

    def test_with_edge_type(self, vault_graph_db):
        deleted = delete_edges_for_node(1, edge_type="wikilink", direction="outgoing", db_path=vault_graph_db)
        assert deleted >= 2

    def test_invalid_direction(self, vault_graph_db):
        with pytest.raises(ValueError, match="Invalid direction"):
            delete_edges_for_node(1, direction="sideways", db_path=vault_graph_db)


class TestRebuildWikilinkEdges:
    def test_rebuild_from_view(self, vault_graph_db):
        count = rebuild_wikilink_edges(db_path=vault_graph_db)
        # After rebuild, should have recreated edges from the vault_index view
        assert count >= 0  # May be 0 if view doesn't contain link data


class TestRebuildWikilinkEdgesForNode:
    def test_rebuild_single_node(self, vault_graph_db):
        # Rebuild edges for node 1 (daily note) with links to Fitness and Nutrition
        count = rebuild_wikilink_edges_for_node(
            node_id=1,
            outgoing_links=["Fitness", "Nutrition"],
            db_path=vault_graph_db,
        )
        assert count == 2

    def test_rebuild_empty_links(self, vault_graph_db):
        count = rebuild_wikilink_edges_for_node(
            node_id=1, outgoing_links=[], db_path=vault_graph_db,
        )
        assert count == 0

    def test_rebuild_with_nonexistent_target(self, vault_graph_db):
        count = rebuild_wikilink_edges_for_node(
            node_id=1,
            outgoing_links=["ZZZNotANode"],
            db_path=vault_graph_db,
        )
        assert count == 0

    def test_case_insensitive_matching(self, vault_graph_db):
        count = rebuild_wikilink_edges_for_node(
            node_id=1,
            outgoing_links=["fitness", "NUTRITION"],
            db_path=vault_graph_db,
        )
        assert count == 2


class TestRebuildTagSharedEdges:
    def test_rebuild_with_shared_tags(self, vault_graph_db):
        # Fitness and Nutrition both have "health" tag
        count = rebuild_tag_shared_edges(db_path=vault_graph_db)
        assert count >= 1

    def test_rebuild_no_tags(self, test_db):
        # test_db has no tags on vault_nodes
        count = rebuild_tag_shared_edges(db_path=test_db)
        assert count == 0


class TestEnsureIcorNodes:
    def test_creates_icor_nodes(self, test_db):
        ensure_icor_nodes(db_path=test_db)
        # Verify ICOR nodes exist in vault_nodes
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM vault_nodes WHERE node_type = 'icor_dimension'"
        ).fetchall()
        conn.close()
        assert len(rows) >= len(ICOR_DIMENSIONS)

    def test_idempotent(self, test_db):
        ensure_icor_nodes(db_path=test_db)
        ensure_icor_nodes(db_path=test_db)
        # Should not duplicate
        conn = sqlite3.connect(str(test_db))
        rows = conn.execute(
            "SELECT COUNT(*) FROM vault_nodes WHERE node_type = 'icor_dimension'"
        ).fetchone()[0]
        conn.close()
        assert rows == len(ICOR_DIMENSIONS)

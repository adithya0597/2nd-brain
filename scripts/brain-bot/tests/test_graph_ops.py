"""Tests for core.graph_ops — vault graph node/edge CRUD operations."""
import contextlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Path & module setup
# ---------------------------------------------------------------------------
SLACK_BOT_DIR = Path(__file__).parent.parent
if str(SLACK_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(SLACK_BOT_DIR))

sys.modules.setdefault("config", MagicMock())


# Provide a working get_connection (real SQLite, not MagicMock)
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
    """Open a connection with FK enforcement."""
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    return c


def _count(db_path, table):
    c = sqlite3.connect(str(db_path))
    return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ===========================================================================
# Node CRUD
# ===========================================================================


class TestUpsertNode:
    """Test node insert and update operations."""

    def test_upsert_node_creates_new(self, test_db):
        """Inserting a new node should create a row in vault_nodes."""
        from core import graph_ops

        graph_ops.upsert_node(
            file_path="Concepts/Test.md",
            title="Test",
            type="concept",
            frontmatter={"status": "seedling"},
            tags=["test"],
            word_count=100,
            last_modified="2026-03-01T10:00:00",
            db_path=test_db,
        )

        conn = _conn(test_db)
        row = conn.execute(
            "SELECT * FROM vault_nodes WHERE file_path=?", ("Concepts/Test.md",)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["title"] == "Test"
        assert row["type"] == "concept"
        assert row["word_count"] == 100
        assert row["node_type"] == "document"

    def test_upsert_node_updates_existing(self, test_db):
        """Upserting same file_path should update, not duplicate."""
        from core import graph_ops

        graph_ops.upsert_node(
            file_path="Concepts/Test.md",
            title="Test",
            type="concept",
            word_count=100,
            db_path=test_db,
        )
        # Update with new word count and title
        graph_ops.upsert_node(
            file_path="Concepts/Test.md",
            title="Test Updated",
            type="concept",
            frontmatter={"status": "growing"},
            tags=["test", "updated"],
            word_count=200,
            last_modified="2026-03-02T10:00:00",
            db_path=test_db,
        )

        conn = _conn(test_db)
        rows = conn.execute(
            "SELECT * FROM vault_nodes WHERE file_path=?", ("Concepts/Test.md",)
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["title"] == "Test Updated"
        assert rows[0]["word_count"] == 200


class TestDeleteNode:

    def test_delete_node_cascades_edges(self, vault_graph_db):
        """Deleting a node should cascade-delete its edges."""
        from core import graph_ops

        # Node 2 (Fitness) has edges: 1->2, 2->3
        edges_before = _count(vault_graph_db, "vault_edges")
        assert edges_before == 4  # 1->2, 1->3, 2->3, 4->5

        graph_ops.delete_node(file_path="Concepts/Fitness.md", db_path=vault_graph_db)

        # Node should be gone
        conn = _conn(vault_graph_db)
        node = conn.execute(
            "SELECT * FROM vault_nodes WHERE file_path='Concepts/Fitness.md'"
        ).fetchone()
        assert node is None

        # Edges involving node 2 should be gone (1->2 and 2->3)
        edges_after = conn.execute("SELECT COUNT(*) FROM vault_edges").fetchone()[0]
        conn.close()
        assert edges_after == 2  # 1->3 and 4->5 remain


class TestGetNode:

    def test_get_node_by_path(self, vault_graph_db):
        """Query node by file_path."""
        from core import graph_ops

        node = graph_ops.get_node_by_path(
            "Concepts/Fitness.md", db_path=vault_graph_db
        )

        assert node is not None
        assert node["title"] == "Fitness"
        assert node["type"] == "concept"

    def test_get_node_by_path_missing(self, vault_graph_db):
        """Querying nonexistent path returns None."""
        from core import graph_ops

        node = graph_ops.get_node_by_path(
            "Nonexistent.md", db_path=vault_graph_db
        )
        assert node is None

    def test_get_node_by_title(self, vault_graph_db):
        """Query node by title."""
        from core import graph_ops

        node = graph_ops.get_node_by_title(
            "Nutrition", db_path=vault_graph_db
        )

        assert node is not None
        assert node["file_path"] == "Concepts/Nutrition.md"

    def test_get_node_by_title_missing(self, vault_graph_db):
        """Querying nonexistent title returns None."""
        from core import graph_ops

        node = graph_ops.get_node_by_title(
            "NonexistentTitle", db_path=vault_graph_db
        )
        assert node is None


# ===========================================================================
# Edge CRUD
# ===========================================================================


class TestUpsertEdge:

    def test_upsert_edge(self, vault_graph_db):
        """Create an edge and verify fields."""
        from core import graph_ops

        graph_ops.upsert_edge(
            source_id=3,
            target_id=5,
            edge_type="semantic_similarity",
            weight=0.85,
            metadata={"reason": "test"},
            db_path=vault_graph_db,
        )

        conn = _conn(vault_graph_db)
        edge = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=3 AND target_node_id=5 AND edge_type='semantic_similarity'"
        ).fetchone()
        conn.close()

        assert edge is not None
        assert edge["weight"] == 0.85
        assert json.loads(edge["metadata_json"])["reason"] == "test"

    def test_upsert_edge_unique_constraint(self, vault_graph_db):
        """Same source/target/type should update weight, not create duplicate."""
        from core import graph_ops

        graph_ops.upsert_edge(
            source_id=3,
            target_id=5,
            edge_type="semantic_similarity",
            weight=0.5,
            db_path=vault_graph_db,
        )
        graph_ops.upsert_edge(
            source_id=3,
            target_id=5,
            edge_type="semantic_similarity",
            weight=0.9,
            db_path=vault_graph_db,
        )

        conn = _conn(vault_graph_db)
        edges = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=3 AND target_node_id=5 AND edge_type='semantic_similarity'"
        ).fetchall()
        conn.close()

        assert len(edges) == 1
        assert edges[0]["weight"] == 0.9


class TestDeleteEdges:

    def test_delete_edges_outgoing(self, vault_graph_db):
        """Delete only outgoing edges for node 1."""
        from core import graph_ops

        graph_ops.delete_edges_for_node(1, direction="outgoing", db_path=vault_graph_db)

        conn = _conn(vault_graph_db)
        # Node 1 had outgoing: 1->2, 1->3. Both should be gone.
        outgoing = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=1"
        ).fetchall()
        # Edges not involving node 1 as source should remain: 2->3, 4->5
        remaining = conn.execute("SELECT * FROM vault_edges").fetchall()
        conn.close()

        assert len(outgoing) == 0
        assert len(remaining) == 2  # 2->3 and 4->5

    def test_delete_edges_incoming(self, vault_graph_db):
        """Delete only incoming edges for node 3 (Nutrition)."""
        from core import graph_ops

        graph_ops.delete_edges_for_node(3, direction="incoming", db_path=vault_graph_db)

        conn = _conn(vault_graph_db)
        # Node 3 had incoming: 1->3, 2->3. Both should be gone.
        incoming = conn.execute(
            "SELECT * FROM vault_edges WHERE target_node_id=3"
        ).fetchall()
        # 1->2 and 4->5 should remain
        remaining = conn.execute("SELECT * FROM vault_edges").fetchall()
        conn.close()

        assert len(incoming) == 0
        assert len(remaining) == 2

    def test_delete_edges_by_type(self, vault_graph_db):
        """Delete only edges of a specific type."""
        from core import graph_ops

        # First add a non-wikilink edge
        conn = _conn(vault_graph_db)
        conn.execute(
            "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type, weight) "
            "VALUES (1, 5, 'semantic_similarity', 0.7)"
        )
        conn.commit()

        total_before = conn.execute("SELECT COUNT(*) FROM vault_edges").fetchone()[0]
        assert total_before == 5  # 4 wikilinks + 1 semantic_similarity
        conn.close()

        graph_ops.delete_edges_for_node(
            1, edge_type="wikilink", direction="outgoing", db_path=vault_graph_db,
        )

        conn = _conn(vault_graph_db)
        # Only wikilinks from node 1 deleted (1->2, 1->3). semantic_similarity 1->5 remains.
        remaining = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=1"
        ).fetchall()
        conn.close()

        assert len(remaining) == 1
        assert remaining[0]["edge_type"] == "semantic_similarity"


class TestGetEdges:

    def test_get_outgoing_edges(self, vault_graph_db):
        """Get outgoing edges with joined target node info."""
        from core import graph_ops

        edges = graph_ops.get_outgoing_edges(node_id=1, db_path=vault_graph_db)

        assert len(edges) == 2
        target_titles = {e["target_title"] for e in edges}
        assert target_titles == {"Fitness", "Nutrition"}

    def test_get_incoming_edges(self, vault_graph_db):
        """Get incoming edges with joined source node info."""
        from core import graph_ops

        edges = graph_ops.get_incoming_edges(node_id=3, db_path=vault_graph_db)

        # Node 3 (Nutrition) has incoming from node 1 (daily) and node 2 (Fitness)
        assert len(edges) == 2
        source_titles = {e["source_title"] for e in edges}
        assert source_titles == {"2026-03-01", "Fitness"}


# ===========================================================================
# Graph Traversal
# ===========================================================================


class TestGetNeighbors:

    def test_get_neighbors_depth_1(self, vault_graph_db):
        """BFS at depth=1 returns direct neighbors only."""
        from core import graph_ops

        neighbors = graph_ops.get_neighbors(
            node_id=1, depth=1, db_path=vault_graph_db
        )

        # Node 1 links to 2 (Fitness) and 3 (Nutrition)
        neighbor_ids = {n["id"] for n in neighbors}
        assert neighbor_ids == {2, 3}
        # All should be hop 1
        for n in neighbors:
            assert n["_hop"] == 1

    def test_get_neighbors_depth_2(self, vault_graph_db):
        """BFS at depth=2 finds 2-hop neighbors."""
        from core import graph_ops

        neighbors = graph_ops.get_neighbors(
            node_id=1, depth=2, db_path=vault_graph_db
        )

        neighbor_ids = {n["id"] for n in neighbors}
        # Depth 1: node 2 (Fitness), node 3 (Nutrition)
        # Depth 2: nothing new (all reachable nodes already visited)
        assert 2 in neighbor_ids
        assert 3 in neighbor_ids
        hop_values = {n["_hop"] for n in neighbors}
        assert 1 in hop_values

    def test_get_neighbors_with_edge_types(self, vault_graph_db):
        """Filter BFS to specific edge types."""
        from core import graph_ops

        # Add a semantic_similarity edge from node 1 to node 5
        conn = _conn(vault_graph_db)
        conn.execute(
            "INSERT INTO vault_edges (source_node_id, target_node_id, edge_type, weight) "
            "VALUES (1, 5, 'semantic_similarity', 0.8)"
        )
        conn.commit()
        conn.close()

        # Only follow semantic_similarity edges
        neighbors = graph_ops.get_neighbors(
            node_id=1, depth=1, edge_types=["semantic_similarity"],
            db_path=vault_graph_db,
        )

        neighbor_ids = {n["id"] for n in neighbors}
        assert neighbor_ids == {5}  # Only Side-Project via semantic_similarity edge


# ===========================================================================
# Bulk Operations
# ===========================================================================


class TestBulkUpsertEdges:

    def test_bulk_upsert_edges(self, test_db):
        """Bulk insert multiple edges at once."""
        from core import graph_ops

        # First create some nodes
        conn = _conn(test_db)
        for fp, title in [("a.md", "A"), ("b.md", "B"), ("c.md", "C"), ("d.md", "D")]:
            conn.execute(
                "INSERT INTO vault_nodes (file_path, title, type) VALUES (?, ?, '')",
                (fp, title),
            )
        conn.commit()
        conn.close()

        edges = [
            {"source_node_id": 1, "target_node_id": 2, "edge_type": "wikilink"},
            {"source_node_id": 1, "target_node_id": 3, "edge_type": "wikilink"},
            {"source_node_id": 2, "target_node_id": 4, "edge_type": "semantic_similarity", "weight": 0.7},
            {"source_node_id": 3, "target_node_id": 4, "edge_type": "wikilink"},
        ]

        count = graph_ops.bulk_upsert_edges(edges, db_path=test_db)

        assert count == 4
        assert _count(test_db, "vault_edges") == 4


# ===========================================================================
# ICOR Node Management
# ===========================================================================


class TestEnsureIcorNodes:

    def test_ensure_icor_nodes_creates_six(self, test_db):
        """ensure_icor_nodes should create 6 ICOR dimension nodes."""
        from core import graph_ops

        graph_ops.ensure_icor_nodes(db_path=test_db)

        conn = _conn(test_db)
        icor_nodes = conn.execute(
            "SELECT * FROM vault_nodes WHERE node_type='icor_dimension'"
        ).fetchall()
        conn.close()

        assert len(icor_nodes) == 6
        names = {n["title"] for n in icor_nodes}
        assert names == {
            "Health & Vitality",
            "Wealth & Finance",
            "Relationships",
            "Mind & Growth",
            "Purpose & Impact",
            "Systems & Environment",
        }

    def test_ensure_icor_nodes_idempotent(self, test_db):
        """Running ensure_icor_nodes twice should not create duplicates."""
        from core import graph_ops

        graph_ops.ensure_icor_nodes(db_path=test_db)
        graph_ops.ensure_icor_nodes(db_path=test_db)

        conn = _conn(test_db)
        icor_count = conn.execute(
            "SELECT COUNT(*) FROM vault_nodes WHERE node_type='icor_dimension'"
        ).fetchone()[0]
        conn.close()

        assert icor_count == 6


# ===========================================================================
# Wikilink Edge Rebuild
# ===========================================================================


class TestRebuildWikilinkEdges:

    def test_rebuild_wikilink_edges_for_node(self, test_db):
        """rebuild_wikilink_edges_for_node should create edges from link list."""
        from core import graph_ops

        # Create source and target nodes
        conn = _conn(test_db)
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type) VALUES (?, ?, ?)",
            ("Daily Notes/2026-03-05.md", "2026-03-05", "journal"),
        )
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type) VALUES (?, ?, ?)",
            ("Concepts/Fitness.md", "Fitness", "concept"),
        )
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type) VALUES (?, ?, ?)",
            ("Concepts/Nutrition.md", "Nutrition", "concept"),
        )
        conn.execute(
            "INSERT INTO vault_nodes (file_path, title, type) VALUES (?, ?, ?)",
            ("Concepts/Sleep.md", "Sleep", "concept"),
        )
        conn.commit()
        conn.close()

        graph_ops.rebuild_wikilink_edges_for_node(
            node_id=1,
            outgoing_links=["Fitness", "Nutrition", "Sleep"],
            db_path=test_db,
        )

        conn = _conn(test_db)
        edges = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=1 AND edge_type='wikilink'"
        ).fetchall()
        conn.close()

        assert len(edges) == 3
        target_ids = {e["target_node_id"] for e in edges}
        assert target_ids == {2, 3, 4}

    def test_rebuild_wikilink_edges_replaces_old(self, test_db):
        """Rebuilding wikilinks should remove old edges first."""
        from core import graph_ops

        # Create nodes
        conn = _conn(test_db)
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('a.md', 'A', '')")
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('b.md', 'B', '')")
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('c.md', 'C', '')")
        # Old edge: A -> B
        conn.execute("INSERT INTO vault_edges (source_node_id, target_node_id, edge_type) VALUES (1, 2, 'wikilink')")
        conn.commit()
        conn.close()

        # Rebuild: A now links to C only
        graph_ops.rebuild_wikilink_edges_for_node(
            node_id=1,
            outgoing_links=["C"],
            db_path=test_db,
        )

        conn = _conn(test_db)
        edges = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=1 AND edge_type='wikilink'"
        ).fetchall()
        conn.close()

        assert len(edges) == 1
        assert edges[0]["target_node_id"] == 3

    def test_rebuild_wikilink_edges_skips_missing_targets(self, test_db):
        """Links to nonexistent titles should be silently skipped."""
        from core import graph_ops

        conn = _conn(test_db)
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('a.md', 'A', '')")
        conn.execute("INSERT INTO vault_nodes (file_path, title, type) VALUES ('b.md', 'B', '')")
        conn.commit()
        conn.close()

        graph_ops.rebuild_wikilink_edges_for_node(
            node_id=1,
            outgoing_links=["B", "Nonexistent", "AlsoMissing"],
            db_path=test_db,
        )

        conn = _conn(test_db)
        edges = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=1 AND edge_type='wikilink'"
        ).fetchall()
        conn.close()

        assert len(edges) == 1
        assert edges[0]["target_node_id"] == 2

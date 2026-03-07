"""Tests for core.icor_affinity — ICOR dimension affinity scoring and edge management."""
import contextlib
import sqlite3
import struct
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

# Mock config with required attributes
_cfg = sys.modules.get("config") or MagicMock()
_cfg.EMBEDDING_DIM = 384
sys.modules.setdefault("config", _cfg)


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

# Embedding store mocks — applied via fixture to avoid polluting sys.modules
_mock_get_file_embedding = MagicMock(return_value=None)
_mock_get_icor_embeddings = MagicMock(return_value={})


@pytest.fixture(autouse=True)
def _mock_embedding_store():
    """Patch embedding_store functions for icor_affinity tests."""
    _mock_get_file_embedding.reset_mock(return_value=True)
    _mock_get_file_embedding.return_value = None
    _mock_get_icor_embeddings.reset_mock(return_value=True)
    _mock_get_icor_embeddings.return_value = {}
    with patch("core.embedding_store.get_file_embedding", _mock_get_file_embedding), \
         patch("core.embedding_store.get_icor_embeddings", _mock_get_icor_embeddings):
        yield


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ICOR_DIMENSIONS = [
    "Health & Vitality",
    "Wealth & Finance",
    "Relationships",
    "Mind & Growth",
    "Purpose & Impact",
    "Systems & Environment",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    return c


def _make_embedding(*values, dim=384):
    """Create embedding bytes. Specified values fill from index 0, rest padded with 0."""
    padded = list(values) + [0.0] * (dim - len(values))
    return struct.pack(f"{dim}f", *padded[:dim])


def _setup_icor_nodes(db_path):
    """Insert 6 ICOR dimension nodes (matching ensure_icor_nodes format)."""
    conn = _conn(db_path)
    for dim in ICOR_DIMENSIONS:
        conn.execute(
            "INSERT OR IGNORE INTO vault_nodes (file_path, title, type, node_type) "
            "VALUES (?, ?, '', 'icor_dimension')",
            (f"icor://{dim}", dim),
        )
    conn.commit()
    conn.close()


def _setup_doc_node(db_path, file_path="Concepts/Fitness.md", title="Fitness"):
    """Insert a document node and return its id."""
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO vault_nodes (file_path, title, type, node_type) "
        "VALUES (?, ?, 'concept', 'document')",
        (file_path, title),
    )
    conn.commit()
    node_id = conn.execute(
        "SELECT id FROM vault_nodes WHERE file_path=?", (file_path,)
    ).fetchone()[0]
    conn.close()
    return node_id


# ===========================================================================
# Affinity Computation
# ===========================================================================


class TestComputeFileIcorAffinity:
    """Test computing ICOR affinity scores for a file."""

    def test_compute_file_icor_affinity_returns_scores(self, test_db):
        """Affinity computation should return (dimension, score) pairs."""
        _setup_icor_nodes(test_db)
        _setup_doc_node(test_db)

        # File embedding: unit vector along dim 0 → [1, 0, 0, ...]
        file_emb = _make_embedding(1.0, 0.0)

        # ICOR reference embeddings with known cosine similarities:
        # cos(file, ref) ≈ first component of ref (when ref is ~unit length)
        icor_embs = {
            "Health & Vitality": [_make_embedding(0.9, 0.436)],     # cos ≈ 0.9
            "Wealth & Finance": [_make_embedding(0.2, 0.980)],      # cos ≈ 0.2
            "Relationships": [_make_embedding(0.35, 0.937)],        # cos ≈ 0.35
            "Mind & Growth": [_make_embedding(0.1, 0.995)],         # cos ≈ 0.1
            "Purpose & Impact": [_make_embedding(0.5, 0.866)],      # cos ≈ 0.5
            "Systems & Environment": [_make_embedding(0.05, 0.999)], # cos ≈ 0.05
        }

        _mock_get_file_embedding.return_value = file_emb
        _mock_get_icor_embeddings.return_value = icor_embs

        from core import icor_affinity

        scores = icor_affinity.compute_file_icor_affinity(
            file_path="Concepts/Fitness.md",
            db_path=test_db,
        )

        assert isinstance(scores, list)
        assert len(scores) > 0
        for dim_name, score in scores:
            assert isinstance(dim_name, str)
            assert isinstance(score, float)

    def test_affinity_threshold_filtering(self, test_db):
        """Scores below ICOR_AFFINITY_THRESHOLD (0.3) should be excluded."""
        _setup_icor_nodes(test_db)
        _setup_doc_node(test_db)

        file_emb = _make_embedding(1.0, 0.0)
        icor_embs = {
            "Health & Vitality": [_make_embedding(0.9, 0.436)],     # cos ≈ 0.9 ✓
            "Wealth & Finance": [_make_embedding(0.2, 0.980)],      # cos ≈ 0.2 ✗
            "Relationships": [_make_embedding(0.35, 0.937)],        # cos ≈ 0.35 ✓
            "Mind & Growth": [_make_embedding(0.1, 0.995)],         # cos ≈ 0.1 ✗
            "Purpose & Impact": [_make_embedding(0.5, 0.866)],      # cos ≈ 0.5 ✓
            "Systems & Environment": [_make_embedding(0.05, 0.999)], # cos ≈ 0.05 ✗
        }

        _mock_get_file_embedding.return_value = file_emb
        _mock_get_icor_embeddings.return_value = icor_embs

        from core import icor_affinity

        scores = icor_affinity.compute_file_icor_affinity(
            file_path="Concepts/Fitness.md",
            db_path=test_db,
        )

        dims_returned = {s[0] for s in scores}
        # Above threshold (0.3)
        assert "Health & Vitality" in dims_returned
        assert "Relationships" in dims_returned
        assert "Purpose & Impact" in dims_returned
        # Below threshold
        assert "Wealth & Finance" not in dims_returned
        assert "Mind & Growth" not in dims_returned
        assert "Systems & Environment" not in dims_returned

    def test_no_embeddings_returns_empty(self, test_db):
        """When file has no embedding, returns empty list."""
        _mock_get_file_embedding.return_value = None

        from core import icor_affinity

        scores = icor_affinity.compute_file_icor_affinity(
            file_path="Concepts/Fitness.md",
            db_path=test_db,
        )

        assert scores == []


# ===========================================================================
# Edge Management
# ===========================================================================


class TestUpdateIcorEdges:
    """Test creating and updating ICOR affinity edges in vault_edges."""

    def test_update_icor_edges_for_file(self, test_db):
        """Verify edges created in vault_edges with type='icor_affinity'."""
        _setup_icor_nodes(test_db)
        doc_id = _setup_doc_node(test_db)

        file_emb = _make_embedding(1.0, 0.0)
        icor_embs = {
            "Health & Vitality": [_make_embedding(0.9, 0.436)],     # cos ≈ 0.9 ✓
            "Wealth & Finance": [_make_embedding(0.2, 0.980)],      # cos ≈ 0.2 ✗
            "Relationships": [_make_embedding(0.35, 0.937)],        # cos ≈ 0.35 ✓
            "Mind & Growth": [_make_embedding(0.1, 0.995)],         # cos ≈ 0.1 ✗
            "Purpose & Impact": [_make_embedding(0.5, 0.866)],      # cos ≈ 0.5 ✓
            "Systems & Environment": [_make_embedding(0.05, 0.999)], # cos ≈ 0.05 ✗
        }

        _mock_get_file_embedding.return_value = file_emb
        _mock_get_icor_embeddings.return_value = icor_embs

        from core import icor_affinity

        count = icor_affinity.update_icor_edges_for_file(
            file_path="Concepts/Fitness.md",
            db_path=test_db,
        )

        conn = _conn(test_db)
        edges = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=? AND edge_type='icor_affinity'",
            (doc_id,),
        ).fetchall()
        conn.close()

        # 3 dimensions above threshold: Health, Relationships, Purpose
        assert count == 3
        assert len(edges) == 3

    def test_update_icor_edges_replaces_old(self, test_db):
        """Old affinity edges should be deleted before inserting new ones."""
        _setup_icor_nodes(test_db)
        doc_id = _setup_doc_node(test_db)

        from core import icor_affinity

        # First pass: Health and Wealth above threshold
        file_emb = _make_embedding(1.0, 0.0)
        _mock_get_file_embedding.return_value = file_emb
        _mock_get_icor_embeddings.return_value = {
            "Health & Vitality": [_make_embedding(0.9, 0.436)],     # ✓
            "Wealth & Finance": [_make_embedding(0.5, 0.866)],      # ✓
            "Relationships": [_make_embedding(0.1, 0.995)],         # ✗
            "Mind & Growth": [_make_embedding(0.1, 0.995)],         # ✗
            "Purpose & Impact": [_make_embedding(0.1, 0.995)],      # ✗
            "Systems & Environment": [_make_embedding(0.05, 0.999)], # ✗
        }

        icor_affinity.update_icor_edges_for_file(
            file_path="Concepts/Fitness.md", db_path=test_db,
        )

        conn = _conn(test_db)
        first_pass_count = conn.execute(
            "SELECT COUNT(*) FROM vault_edges WHERE source_node_id=? AND edge_type='icor_affinity'",
            (doc_id,),
        ).fetchone()[0]
        conn.close()
        assert first_pass_count == 2

        # Second pass: different affinities (Relationships, Mind, Purpose above)
        _mock_get_icor_embeddings.return_value = {
            "Health & Vitality": [_make_embedding(0.1, 0.995)],     # ✗
            "Wealth & Finance": [_make_embedding(0.1, 0.995)],      # ✗
            "Relationships": [_make_embedding(0.5, 0.866)],         # ✓
            "Mind & Growth": [_make_embedding(0.4, 0.917)],         # ✓
            "Purpose & Impact": [_make_embedding(0.35, 0.937)],     # ✓
            "Systems & Environment": [_make_embedding(0.05, 0.999)], # ✗
        }

        icor_affinity.update_icor_edges_for_file(
            file_path="Concepts/Fitness.md", db_path=test_db,
        )

        conn = _conn(test_db)
        second_pass_edges = conn.execute(
            "SELECT * FROM vault_edges WHERE source_node_id=? AND edge_type='icor_affinity'",
            (doc_id,),
        ).fetchall()
        conn.close()

        # Should have 3 new edges
        assert len(second_pass_edges) == 3

        # Verify old Health & Vitality edge is gone
        conn = _conn(test_db)
        health_id = conn.execute(
            "SELECT id FROM vault_nodes WHERE title='Health & Vitality'"
        ).fetchone()[0]
        conn.close()
        target_ids = {e["target_node_id"] for e in second_pass_edges}
        assert health_id not in target_ids


class TestRebuildAllIcorEdges:
    """Test full rebuild of all ICOR affinity edges."""

    def test_rebuild_all_icor_edges(self, test_db):
        """Full rebuild should process all document nodes."""
        # Don't pre-create ICOR nodes — rebuild_all_icor_edges calls ensure_icor_nodes
        _setup_doc_node(test_db, "Concepts/Fitness.md", "Fitness")
        _setup_doc_node(test_db, "Concepts/Nutrition.md", "Nutrition")
        _setup_doc_node(test_db, "Concepts/Sleep.md", "Sleep")

        # All files get same embedding → same affinity scores
        file_emb = _make_embedding(1.0, 0.0)
        _mock_get_file_embedding.return_value = file_emb
        _mock_get_icor_embeddings.return_value = {
            "Health & Vitality": [_make_embedding(0.9, 0.436)],     # ✓
            "Wealth & Finance": [_make_embedding(0.1, 0.995)],      # ✗
            "Relationships": [_make_embedding(0.1, 0.995)],         # ✗
            "Mind & Growth": [_make_embedding(0.1, 0.995)],         # ✗
            "Purpose & Impact": [_make_embedding(0.1, 0.995)],      # ✗
            "Systems & Environment": [_make_embedding(0.05, 0.999)], # ✗
        }

        from core import icor_affinity

        count = icor_affinity.rebuild_all_icor_edges(db_path=test_db)

        conn = _conn(test_db)
        total_edges = conn.execute(
            "SELECT COUNT(*) FROM vault_edges WHERE edge_type='icor_affinity'"
        ).fetchone()[0]
        conn.close()

        # 3 documents * 1 dimension above threshold each = 3 edges
        assert total_edges == 3
        assert count == 3

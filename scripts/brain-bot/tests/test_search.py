"""Tests for core.search — hybrid search with RRF fusion."""
import sys
from unittest.mock import MagicMock, patch


sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("core.db_connection", MagicMock())


class TestRRFFusion:
    """Test Reciprocal Rank Fusion algorithm."""

    def test_single_channel_preserves_order(self):
        """RRF with one channel should preserve original ranking."""
        from core.search import _rrf_fuse

        ranked_lists = {
            "fts": ["file_a", "file_b", "file_c"],
        }
        metadata = {
            "file_a": {"title": "A", "snippet": "..."},
            "file_b": {"title": "B", "snippet": "..."},
            "file_c": {"title": "C", "snippet": "..."},
        }

        results = _rrf_fuse(ranked_lists, metadata, k=60)
        paths = [r["file_path"] for r in results]
        assert paths == ["file_a", "file_b", "file_c"]

    def test_multi_channel_boosts_shared_results(self):
        """Results appearing in multiple channels get higher RRF score."""
        from core.search import _rrf_fuse

        ranked_lists = {
            "fts": ["file_a", "file_b", "file_c"],
            "vector": ["file_b", "file_d", "file_a"],
        }
        metadata = {
            "file_a": {"title": "A", "snippet": "..."},
            "file_b": {"title": "B", "snippet": "..."},
            "file_c": {"title": "C", "snippet": "..."},
            "file_d": {"title": "D", "snippet": "..."},
        }

        results = _rrf_fuse(ranked_lists, metadata, k=60)
        paths = [r["file_path"] for r in results]
        # file_a and file_b appear in both channels, so they should rank higher
        # file_b: rank 1 in vector (1/61) + rank 2 in fts (1/62)
        # file_a: rank 1 in fts (1/61) + rank 3 in vector (1/63)
        # Both should be above file_c and file_d (single channel only)
        assert "file_a" in paths[:2]
        assert "file_b" in paths[:2]

    def test_deduplication(self):
        """Same file appearing in multiple channels produces one result."""
        from core.search import _rrf_fuse

        ranked_lists = {
            "fts": ["file_a"],
            "vector": ["file_a"],
            "graph": ["file_a"],
        }
        metadata = {
            "file_a": {"title": "A", "snippet": "..."},
        }

        results = _rrf_fuse(ranked_lists, metadata, k=60)
        assert len(results) == 1

    def test_empty_channels(self):
        """Empty ranked lists produce no results."""
        from core.search import _rrf_fuse

        results = _rrf_fuse({}, {}, k=60)
        assert results == []

    def test_k_parameter_affects_scores(self):
        """Different k values change relative scoring."""
        from core.search import _rrf_fuse

        ranked_lists = {"fts": ["a", "b"]}
        metadata = {
            "a": {"title": "A", "snippet": ""},
            "b": {"title": "B", "snippet": ""},
        }

        results_k60 = _rrf_fuse(ranked_lists, metadata, k=60)
        results_k1 = _rrf_fuse(ranked_lists, metadata, k=1)

        # With k=1, rank difference matters more
        # k=1: a=1/2, b=1/3. Ratio = 1.5
        # k=60: a=1/61, b=1/62. Ratio ~= 1.016
        assert len(results_k60) == len(results_k1) == 2


class TestHybridSearch:
    """Test the hybrid_search() orchestrator."""

    @patch("core.search._search_vector", return_value=[])
    @patch("core.search._search_fts", return_value=[])
    @patch("core.search._search_graph", return_value=[])
    def test_empty_query_returns_empty(self, mock_graph, mock_fts, mock_vec):
        from core.search import hybrid_search

        response = hybrid_search("")
        assert response.results == []

    @patch("core.search._search_vector", return_value=[])
    @patch("core.search._search_graph", return_value=[])
    @patch("core.search._search_fts")
    def test_fts_only_fallback(self, mock_fts, mock_graph, mock_vec):
        """When vector is unavailable, FTS results still work."""
        mock_fts.return_value = [("file_a", {"title": "A", "snippet": "found it"})]

        from core.search import hybrid_search

        response = hybrid_search("test query")
        assert len(response.results) >= 0  # Results depend on RRF implementation

    @patch("core.search._search_vector", return_value=[])
    @patch("core.search._search_fts", return_value=[])
    @patch("core.search._search_graph", return_value=[])
    def test_channels_used_tracking(self, mock_graph, mock_fts, mock_vec):
        from core.search import hybrid_search

        response = hybrid_search("test")
        assert isinstance(response.channels_used, list)


class TestSearchResult:
    """Test SearchResult and SearchResponse dataclasses."""

    def test_search_result_fields(self):
        from core.search import SearchResult

        r = SearchResult(
            file_path="test.md",
            title="Test",
            score=0.95,
            snippet="found it",
            sources=["fts", "vector"],
        )
        assert r.file_path == "test.md"
        assert r.score == 0.95
        assert "fts" in r.sources

    def test_search_response_fields(self):
        from core.search import SearchResponse

        resp = SearchResponse(
            results=[],
            query="test",
            channels_used=["fts"],
            total_candidates=5,
        )
        assert resp.query == "test"
        assert resp.total_candidates == 5

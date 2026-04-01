"""Tests for core.embedding_store — sqlite-vec embedding operations."""
import struct
import sys
from unittest.mock import MagicMock, patch


# Mock config before imports
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("core.db_connection", MagicMock())


class TestSerializeF32:
    """Test vector serialization/deserialization roundtrip."""

    def test_roundtrip_512_dim(self):
        """512-dim vector serializes to 2048 bytes and roundtrips correctly."""
        from core.embedding_store import _serialize_f32, _deserialize_f32

        vector = [float(i) / 512 for i in range(512)]
        packed = _serialize_f32(vector)
        assert len(packed) == 512 * 4  # 2048 bytes

        unpacked = _deserialize_f32(packed, 512)
        for orig, restored in zip(vector, unpacked):
            assert abs(orig - restored) < 1e-6

    def test_empty_vector(self):
        from core.embedding_store import _serialize_f32

        packed = _serialize_f32([])
        assert packed == b""

    def test_known_values(self):
        """Verify specific float packing matches struct.pack."""
        from core.embedding_store import _serialize_f32

        vec = [1.0, -1.0, 0.0, 3.14]
        expected = struct.pack("4f", *vec)
        assert _serialize_f32(vec) == expected


class TestContentHash:
    """Test content hashing for skip-unchanged detection."""

    def test_deterministic(self):
        from core.embedding_store import _content_hash

        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_different_content(self):
        from core.embedding_store import _content_hash

        h1 = _content_hash("hello")
        h2 = _content_hash("world")
        assert h1 != h2

    def test_returns_16_char_hex(self):
        from core.embedding_store import _content_hash

        h = _content_hash("test content")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


class TestCheckVecAvailable:
    """Test sqlite-vec availability detection."""

    def test_available_when_installed(self):
        from core import embedding_store

        embedding_store._VEC_AVAILABLE = None  # Reset cache

        with patch.dict(sys.modules, {"sqlite_vec": MagicMock()}):
            result = embedding_store._check_vec_available()
            assert result is True

    def test_unavailable_when_not_installed(self):
        from core import embedding_store

        embedding_store._VEC_AVAILABLE = None  # Reset cache

        # Remove sqlite_vec from modules to simulate not installed
        with patch.dict(sys.modules, {"sqlite_vec": None}):
            embedding_store._VEC_AVAILABLE = None
            with patch("builtins.__import__", side_effect=ImportError("no sqlite_vec")):
                embedding_store._check_vec_available()
            # Reset for other tests
            embedding_store._VEC_AVAILABLE = None


class TestGetModel:
    """Test thread-safe model singleton."""

    def test_returns_none_when_unavailable(self):
        from core import embedding_store

        embedding_store._embedding_model = None  # Reset

        with patch.dict(sys.modules, {"sentence_transformers": None}):
            embedding_store._embedding_model = None
            with patch("builtins.__import__", side_effect=ImportError):
                model = embedding_store._get_model()
                assert model is None
            embedding_store._embedding_model = None  # Reset sentinel

    def test_returns_cached_model(self):
        from core import embedding_store

        fake_model = MagicMock()
        embedding_store._embedding_model = fake_model

        result = embedding_store._get_model()
        assert result is fake_model
        embedding_store._embedding_model = None  # Reset


class TestEmbedSingleFile:
    """Test single file embedding with mocked model."""

    def test_skips_nonexistent_file(self, tmp_path):
        from core import embedding_store

        result = embedding_store.embed_single_file(
            tmp_path / "nonexistent.md",
            vault_path=tmp_path,
        )
        assert result is False

    def test_skips_non_markdown(self, tmp_path):
        from core import embedding_store

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")

        result = embedding_store.embed_single_file(
            txt_file,
            vault_path=tmp_path,
        )
        assert result is False

    def test_skips_when_model_unavailable(self, tmp_path):
        from core import embedding_store

        embedding_store._embedding_model = False  # Sentinel for "tried but failed"

        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\nSome content")

        result = embedding_store.embed_single_file(md_file, vault_path=tmp_path)
        assert result is False
        embedding_store._embedding_model = None  # Reset


class TestEmbedAllFiles:
    """Test bulk embedding."""

    def test_returns_zero_when_model_unavailable(self, tmp_path):
        from core import embedding_store

        embedding_store._embedding_model = False

        result = embedding_store.embed_all_files(vault_path=tmp_path)
        assert result == 0
        embedding_store._embedding_model = None

    def test_returns_zero_when_vec_unavailable(self, tmp_path):
        from core import embedding_store

        fake_model = MagicMock()
        embedding_store._embedding_model = fake_model
        embedding_store._VEC_AVAILABLE = False

        result = embedding_store.embed_all_files(vault_path=tmp_path)
        assert result == 0

        embedding_store._embedding_model = None
        embedding_store._VEC_AVAILABLE = None


class TestSearchSimilar:
    """Test vector similarity search."""

    def test_returns_empty_when_model_unavailable(self):
        from core import embedding_store

        embedding_store._embedding_model = False

        results = embedding_store.search_similar("test query")
        assert results == []
        embedding_store._embedding_model = None

    def test_returns_empty_when_vec_unavailable(self):
        from core import embedding_store

        fake_model = MagicMock()
        embedding_store._embedding_model = fake_model
        embedding_store._VEC_AVAILABLE = False

        results = embedding_store.search_similar("test query")
        assert results == []

        embedding_store._embedding_model = None
        embedding_store._VEC_AVAILABLE = None

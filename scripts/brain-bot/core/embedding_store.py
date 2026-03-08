"""Persistent vector embedding store using sqlite-vec.

Provides embed/search operations backed by config.EMBEDDING_MODEL
(config.EMBEDDING_DIM dimensions) and sqlite-vec virtual tables.
Gracefully degrades if sqlite-vec is not installed.
"""
import hashlib
import logging
import re
import sqlite3
import struct
import threading
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Thread-safe singleton for the embedding model
_model_lock = threading.Lock()
_embedding_model = None
_VEC_AVAILABLE = None  # None = not yet checked, True/False after check


def _check_vec_available(db_path: Path = None) -> bool:
    """Check if sqlite-vec extension is available."""
    global _VEC_AVAILABLE
    if _VEC_AVAILABLE is not None:
        return _VEC_AVAILABLE
    try:
        import sqlite_vec  # noqa: F401
        _VEC_AVAILABLE = True
    except ImportError:
        logger.warning("sqlite-vec not installed — vector search disabled")
        _VEC_AVAILABLE = False
    return _VEC_AVAILABLE


def _get_model():
    """Thread-safe lazy singleton for the embedding model.

    Returns the SentenceTransformer model or None if unavailable.
    Uses config.EMBEDDING_MODEL (config.EMBEDDING_DIM dimensions).
    """
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model if _embedding_model is not False else None

    with _model_lock:
        # Double-check after acquiring lock
        if _embedding_model is not None:
            return _embedding_model if _embedding_model is not False else None

        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model %s...", config.EMBEDDING_MODEL)
            _embedding_model = SentenceTransformer(config.EMBEDDING_MODEL, trust_remote_code=True)
            logger.info("Embedding model loaded (dim=%d)", config.EMBEDDING_DIM)
            return _embedding_model
        except ImportError:
            logger.warning("sentence-transformers not installed — embeddings disabled")
            _embedding_model = False
            return None
        except Exception:
            logger.exception("Failed to load embedding model")
            _embedding_model = False
            return None


def _serialize_f32(vector) -> bytes:
    """Pack a float vector into bytes for sqlite-vec storage."""
    return struct.pack(f"{len(vector)}f", *vector)


def _deserialize_f32(data: bytes, dim: int = 0) -> list[float]:
    """Unpack bytes back into a float vector."""
    dim = dim or (len(data) // 4)
    return list(struct.unpack(f"{dim}f", data))


def _content_hash(text: str) -> str:
    """SHA-256 hash for skip-unchanged detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _get_vec_connection(db_path: Path = None):
    """Get a raw sqlite3 connection with sqlite-vec loaded.

    NOTE: This returns a raw connection (not a context manager from db_connection)
    because sqlite-vec requires loading the extension before any vec0 operations.
    The caller is responsible for closing the connection.
    """
    if not _check_vec_available():
        return None

    import sqlite_vec
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    # Apply standard PRAGMAs
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def embed_single_file(file_path: Path, vault_path: Path = None, db_path: Path = None) -> bool:
    """Incrementally embed a single vault file.

    Skips re-embedding if content hash is unchanged.
    Called by vault_ops post-write hooks.

    Returns True if the file was (re-)embedded, False otherwise.
    """
    model = _get_model()
    if model is None:
        return False

    vault_path = vault_path or config.VAULT_PATH
    db_path = db_path or config.DB_PATH

    if not file_path.is_absolute():
        file_path = vault_path / file_path

    if not file_path.exists() or not file_path.suffix == ".md":
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, IOError):
        return False

    rel_path = str(file_path.relative_to(vault_path))
    title = file_path.stem
    new_hash = _content_hash(content)

    conn = _get_vec_connection(db_path)
    if conn is None:
        return False

    try:
        # Check if content has changed
        row = conn.execute(
            "SELECT rowid, content_hash FROM vec_vault WHERE file_path = ?",
            (rel_path,),
        ).fetchone()

        if row and row["content_hash"] == new_hash:
            return False  # Content unchanged

        # Strip frontmatter for cleaner embeddings
        body = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", content, flags=re.DOTALL).strip()
        if not body:
            return False

        # Truncate to ~512 tokens worth of text for embedding quality
        embed_text = body[:2000]

        # Generate embedding
        vector = model.encode([embed_text])[0]
        vec_bytes = _serialize_f32(vector)

        # Delete old entry if exists
        if row:
            conn.execute("DELETE FROM vec_vault WHERE rowid = ?", (row["rowid"],))

        # Insert new entry
        conn.execute(
            "INSERT INTO vec_vault (embedding, file_path, title, content_hash) VALUES (?, ?, ?, ?)",
            (vec_bytes, rel_path, title, new_hash),
        )
        conn.commit()
        logger.debug("Embedded: %s", rel_path)
        return True
    except Exception:
        logger.debug("Failed to embed %s", rel_path, exc_info=True)
        return False
    finally:
        conn.close()


def embed_all_files(vault_path: Path = None, db_path: Path = None, force: bool = False) -> int:
    """Bulk-embed all vault markdown files.

    Skips unchanged files unless force=True.
    Called at bot startup.

    Returns the number of files embedded (new or updated).
    """
    model = _get_model()
    if model is None:
        return 0

    vault_path = vault_path or config.VAULT_PATH
    db_path = db_path or config.DB_PATH

    conn = _get_vec_connection(db_path)
    if conn is None:
        return 0

    try:
        # Check model version - if changed, force re-embed all
        stored_model = conn.execute(
            "SELECT value FROM embedding_state WHERE key = 'model_name'"
        ).fetchone()

        if stored_model and stored_model["value"] != config.EMBEDDING_MODEL:
            logger.info("Model changed from %s to %s — forcing re-embed",
                        stored_model["value"], config.EMBEDDING_MODEL)
            force = True

        # Get existing hashes for skip-unchanged detection
        existing_hashes = {}
        if not force:
            for row in conn.execute("SELECT file_path, content_hash FROM vec_vault").fetchall():
                existing_hashes[row["file_path"]] = row["content_hash"]

        # Scan vault files
        frontmatter_re = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)

        files_to_embed = []
        for md_file in sorted(vault_path.rglob("*.md")):
            rel = md_file.relative_to(vault_path)
            if any(part.startswith(".") for part in rel.parts):
                continue

            rel_path = str(rel)
            try:
                content = md_file.read_text(encoding="utf-8")
            except (OSError, IOError):
                continue

            new_hash = _content_hash(content)
            if not force and existing_hashes.get(rel_path) == new_hash:
                continue

            body = frontmatter_re.sub("", content).strip()
            if not body:
                continue

            files_to_embed.append({
                "rel_path": rel_path,
                "title": md_file.stem,
                "body": body[:2000],
                "hash": new_hash,
            })

        if not files_to_embed:
            # Still update model version
            conn.execute(
                "INSERT OR REPLACE INTO embedding_state (key, value) VALUES ('model_name', ?)",
                (config.EMBEDDING_MODEL,),
            )
            conn.commit()
            return 0

        # Batch encode for efficiency
        texts = [f["body"] for f in files_to_embed]
        vectors = model.encode(texts, show_progress_bar=False, batch_size=64)

        if force:
            conn.execute("DELETE FROM vec_vault")

        count = 0
        for file_info, vector in zip(files_to_embed, vectors):
            vec_bytes = _serialize_f32(vector)

            # Delete existing entry
            if not force:
                conn.execute("DELETE FROM vec_vault WHERE file_path = ?", (file_info["rel_path"],))

            conn.execute(
                "INSERT INTO vec_vault (embedding, file_path, title, content_hash) VALUES (?, ?, ?, ?)",
                (vec_bytes, file_info["rel_path"], file_info["title"], file_info["hash"]),
            )
            count += 1

        # Update model version
        conn.execute(
            "INSERT OR REPLACE INTO embedding_state (key, value) VALUES ('model_name', ?)",
            (config.EMBEDDING_MODEL,),
        )
        conn.commit()
        logger.info("Embedded %d vault files (total: %d)", count,
                     conn.execute("SELECT COUNT(*) FROM vec_vault").fetchone()[0])
        return count
    except Exception:
        logger.exception("Bulk embedding failed")
        return 0
    finally:
        conn.close()


def seed_icor_embeddings(db_path: Path = None) -> int:
    """Pre-compute ICOR dimension reference embeddings into vec_icor.

    Uses the same dimension reference texts from classifier.py but
    stores them persistently for fast cosine similarity lookups.

    Returns number of reference embeddings created.
    """
    model = _get_model()
    if model is None:
        return 0

    db_path = db_path or config.DB_PATH
    conn = _get_vec_connection(db_path)
    if conn is None:
        return 0

    try:
        # Import dimension references from classifier
        from core.classifier import _DIMENSION_REFERENCES

        conn.execute("DELETE FROM vec_icor")

        count = 0
        for dimension, ref_texts in _DIMENSION_REFERENCES.items():
            vectors = model.encode(ref_texts, show_progress_bar=False)
            for text, vector in zip(ref_texts, vectors):
                vec_bytes = _serialize_f32(vector)
                conn.execute(
                    "INSERT INTO vec_icor (embedding, dimension, reference_text) VALUES (?, ?, ?)",
                    (vec_bytes, dimension, text),
                )
                count += 1

        conn.commit()
        logger.info("Seeded %d ICOR reference embeddings", count)
        return count
    except Exception:
        logger.exception("ICOR embedding seeding failed")
        return 0
    finally:
        conn.close()


def search_similar(query_text: str, limit: int = 10, db_path: Path = None,
                   metadata_filters=None) -> list[dict]:
    """Search for vault files similar to query text using vector similarity.

    Args:
        query_text: Text to search for.
        limit: Max results to return.
        db_path: Database path.
        metadata_filters: Optional MetadataFilters for pre-filtering.

    Returns:
        List of dicts ``[{file_path, title, distance, rowid}]``
        sorted by distance (closest first). Returns ``[]`` if unavailable.
    """
    model = _get_model()
    if model is None:
        return []

    db_path = db_path or config.DB_PATH
    conn = _get_vec_connection(db_path)
    if conn is None:
        return []

    try:
        query_vector = model.encode([query_text])[0]
        vec_bytes = _serialize_f32(query_vector)

        # Attempt filtered search when metadata_filters are provided
        if metadata_filters is not None:
            try:
                from core.search_filters import is_selective, build_filter_cte
                if is_selective(metadata_filters):
                    cte_sql, cte_params = build_filter_cte(metadata_filters)
                    sql = f"""{cte_sql}
                        SELECT vec_vault.rowid, vec_vault.distance,
                               vec_vault.file_path, vec_vault.title
                        FROM vec_vault
                        INNER JOIN filtered_docs
                            ON vec_vault.file_path = filtered_docs.file_path
                        WHERE vec_vault.embedding MATCH ? AND k = ?
                        ORDER BY vec_vault.distance"""
                    rows = conn.execute(
                        sql, (*cte_params, vec_bytes, limit)
                    ).fetchall()
                    return [
                        {
                            "file_path": r["file_path"],
                            "title": r["title"],
                            "distance": r["distance"],
                            "rowid": r["rowid"],
                        }
                        for r in rows
                    ]
            except ImportError:
                pass  # Fall through to unfiltered search

        # Unfiltered search (default / fallback)
        rows = conn.execute(
            "SELECT rowid, distance, file_path, title "
            "FROM vec_vault WHERE embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (vec_bytes, limit),
        ).fetchall()

        return [
            {
                "file_path": r["file_path"],
                "title": r["title"],
                "distance": r["distance"],
                "rowid": r["rowid"],
            }
            for r in rows
        ]
    except Exception:
        logger.debug("Vector search failed", exc_info=True)
        return []
    finally:
        conn.close()


def get_file_embedding(file_path: str, db_path: Path = None) -> bytes | None:
    """Get the raw embedding bytes for a vault file.

    Args:
        file_path: Relative path within the vault (e.g. ``"Daily Notes/2026-03-06.md"``).
        db_path: Optional override for the database path.

    Returns:
        The serialized float vector bytes (dimension determined by
        config.EMBEDDING_DIM), or ``None`` if not found or if sqlite-vec
        is unavailable.
    """
    conn = _get_vec_connection(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT embedding FROM vec_vault WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return row["embedding"] if row else None
    except Exception:
        logger.debug("Failed to get embedding for %s", file_path, exc_info=True)
        return None
    finally:
        conn.close()


def get_icor_embeddings(db_path: Path = None) -> dict[str, list[bytes]]:
    """Get all ICOR reference embeddings grouped by dimension.

    Returns:
        ``{dimension_name: [embedding_bytes, ...]}`` where each
        ``embedding_bytes`` is a serialized float vector (dimension
        determined by config.EMBEDDING_DIM). Returns ``{}`` if
        sqlite-vec is unavailable or no ICOR embeddings have been seeded.
    """
    conn = _get_vec_connection(db_path)
    if conn is None:
        return {}
    try:
        rows = conn.execute(
            "SELECT dimension, embedding FROM vec_icor ORDER BY dimension"
        ).fetchall()
        result: dict[str, list[bytes]] = {}
        for row in rows:
            result.setdefault(row["dimension"], []).append(row["embedding"])
        return result
    except Exception:
        logger.debug("Failed to get ICOR embeddings", exc_info=True)
        return {}
    finally:
        conn.close()

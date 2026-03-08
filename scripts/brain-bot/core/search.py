"""Hybrid search: Vector + Chunk-Vector + FTS5 + Graph with Reciprocal Rank Fusion.

Provides fast search across the entire Second Brain vault using four
complementary search channels, fused with RRF for optimal ranking.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    file_path: str
    title: str
    score: float
    snippet: str
    sources: list[str] = field(default_factory=list)


@dataclass
class SearchResponse:
    """Complete response from hybrid_search()."""
    results: list[SearchResult]
    query: str
    channels_used: list[str]
    total_candidates: int


def _search_vector(query_text: str, limit: int = 20, db_path: Path = None, metadata_filters=None) -> list[tuple[str, dict]]:
    """Search using vector similarity via embedding_store.

    Returns [(file_path, {title, snippet, distance})] ordered by relevance.
    Gracefully returns [] if sqlite-vec unavailable.
    """
    try:
        from core.embedding_store import search_similar
        results = search_similar(query_text, limit=limit, db_path=db_path, metadata_filters=metadata_filters)
        return [
            (r["file_path"], {
                "title": r["title"],
                "snippet": f"(similarity: {1 - r['distance']:.2f})",
                "distance": r["distance"],
            })
            for r in results
        ]
    except Exception:
        logger.debug("Vector search unavailable", exc_info=True)
        return []


def _search_chunks(query_text: str, limit: int = 20, db_path: Path = None) -> list[tuple[str, dict]]:
    """Search using chunk-level vector similarity.

    Returns file-level results (deduplicated from chunks).
    If a file has multiple matching chunks, keeps the best match
    and notes the matching section in the snippet.
    """
    try:
        from core.chunk_embedder import search_chunks
        results = search_chunks(query_text, limit=limit, db_path=db_path)

        # Deduplicate to file level (keep best chunk per file)
        seen_files: dict[str, dict] = {}
        for r in results:
            fp = r["file_path"]
            if fp not in seen_files or r["distance"] < seen_files[fp]["distance"]:
                seen_files[fp] = r

        return [
            (fp, {
                "title": info["title"],
                "snippet": (
                    f"(chunk: {info['section_header'] or 'section ' + str(info['chunk_index'])}"
                    f", sim: {1 - info['distance']:.2f})"
                ),
                "distance": info["distance"],
            })
            for fp, info in seen_files.items()
        ]
    except Exception:
        logger.debug("Chunk search unavailable", exc_info=True)
        return []


def _search_fts(query_text: str, limit: int = 20, db_path: str = None) -> list[tuple[str, dict]]:
    """Search using FTS5 full-text search.

    Returns [(file_path, {title, snippet, rank})] ordered by BM25 rank.
    """
    try:
        from core.fts_index import search_fts
        results = search_fts(query_text, limit=limit, db_path=db_path)
        return [
            (r["file_path"], {
                "title": r["title"],
                "snippet": r.get("snippet", ""),
                "rank": r.get("rank", 0),
            })
            for r in results
        ]
    except Exception:
        logger.debug("FTS search failed", exc_info=True)
        return []


def _search_graph(query_text: str, limit: int = 15, db_path: Path = None) -> list[tuple[str, dict]]:
    """Search using vault graph (title/link mentions + 1-hop expansion).

    Returns [(file_path, {title, snippet})] for files connected to the query topic.
    Implements super-node trap: if seed matches >50% of vault, skip graph channel.
    """
    try:
        from core.vault_indexer import find_files_mentioning, get_linked_files
        from core.db_connection import get_connection
        import sqlite3

        # Get total vault file count for super-node detection
        with get_connection(db_path, row_factory=sqlite3.Row) as conn:
            total_count = conn.execute(
                "SELECT COUNT(*) as c FROM vault_nodes WHERE node_type='document'"
            ).fetchone()["c"]

        seed_files = find_files_mentioning(query_text, db_path=db_path)

        # Super-node trap: if seed matches >50% of vault, skip graph
        if total_count > 0 and len(seed_files) > total_count * 0.5:
            logger.debug("Graph super-node trap: %d/%d files matched, skipping",
                        len(seed_files), total_count)
            return []

        seed_titles = [r["title"] for r in seed_files[:10]]
        if not seed_titles:
            return []

        # 1-hop expansion
        linked = get_linked_files(seed_titles, depth=1, db_path=db_path)

        results = []
        seen = set()
        for row in linked[:limit]:
            fp = row.get("file_path", "")
            if not fp or fp in seen:
                continue
            seen.add(fp)
            results.append((fp, {
                "title": row.get("title", ""),
                "snippet": f"(graph: hop {row.get('_hop', 0)})",
            }))

        return results
    except Exception:
        logger.debug("Graph search failed", exc_info=True)
        return []


def _rrf_fuse(
    ranked_lists: dict[str, list[str]],
    metadata: dict[str, dict],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion across multiple ranked lists.

    Args:
        ranked_lists: {channel_name: [file_path ordered by rank]}
        metadata: {file_path: {title, snippet, ...}}
        k: RRF constant (default 60, higher = more uniform weighting)

    Returns:
        List of dicts: [{file_path, title, snippet, score, sources}]
        sorted by descending RRF score.
    """
    scores: dict[str, float] = {}
    sources: dict[str, list[str]] = {}

    for channel, file_paths in ranked_lists.items():
        for rank, fp in enumerate(file_paths):
            rrf_score = 1.0 / (k + rank + 1)
            scores[fp] = scores.get(fp, 0.0) + rrf_score
            sources.setdefault(fp, []).append(channel)

    # Sort by descending score
    sorted_fps = sorted(scores.keys(), key=lambda fp: scores[fp], reverse=True)

    results = []
    for fp in sorted_fps:
        meta = metadata.get(fp, {})
        results.append({
            "file_path": fp,
            "title": meta.get("title", fp),
            "snippet": meta.get("snippet", ""),
            "score": round(scores[fp], 6),
            "sources": sources.get(fp, []),
        })

    return results


def hybrid_search(
    query_text: str,
    limit: int = 20,
    channels: list[str] | None = None,
    k: int = 60,
    db_path: Path = None,
    metadata_filters=None,
) -> SearchResponse:
    """Main hybrid search entry point.

    Searches across vector, chunks, FTS, and graph channels, then fuses with RRF.

    Args:
        query_text: The search query.
        limit: Maximum results to return.
        channels: Optional list of channels to use (default: all available).
                  Valid channels: "vector", "chunks", "fts", "graph"
        k: RRF constant.
        db_path: Optional DB path override.
        metadata_filters: Optional MetadataFilters to narrow vector search
            results by frontmatter attributes (type, status, date range, etc.).
            Only applied to the vector channel; FTS and graph have their own
            filtering logic.

    Returns:
        SearchResponse with ranked, deduplicated results.
    """
    if not query_text or not query_text.strip():
        return SearchResponse(results=[], query=query_text or "", channels_used=[], total_candidates=0)

    active_channels = channels or ["vector", "chunks", "fts", "graph"]
    db_path = db_path or config.DB_PATH

    # Run search channels
    ranked_lists: dict[str, list[str]] = {}
    metadata: dict[str, dict] = {}
    channels_used = []

    if "vector" in active_channels:
        vec_results = _search_vector(query_text, limit=limit, db_path=db_path, metadata_filters=metadata_filters)
        if vec_results:
            ranked_lists["vector"] = [fp for fp, _ in vec_results]
            for fp, meta in vec_results:
                metadata.setdefault(fp, {}).update(meta)
            channels_used.append("vector")

    if "chunks" in active_channels:
        chunk_results = _search_chunks(query_text, limit=limit, db_path=db_path)
        if chunk_results:
            ranked_lists["chunks"] = [fp for fp, _ in chunk_results]
            for fp, meta in chunk_results:
                metadata.setdefault(fp, {}).update(meta)
            channels_used.append("chunks")

    if "fts" in active_channels:
        fts_results = _search_fts(query_text, limit=limit, db_path=str(db_path))
        if fts_results:
            ranked_lists["fts"] = [fp for fp, _ in fts_results]
            for fp, meta in fts_results:
                # FTS snippets are usually better -- prefer them
                if fp not in metadata or not metadata[fp].get("snippet"):
                    metadata.setdefault(fp, {}).update(meta)
                else:
                    metadata[fp]["title"] = meta.get("title") or metadata[fp].get("title", "")
            channels_used.append("fts")

    if "graph" in active_channels:
        graph_results = _search_graph(query_text, limit=limit, db_path=db_path)
        if graph_results:
            ranked_lists["graph"] = [fp for fp, _ in graph_results]
            for fp, meta in graph_results:
                metadata.setdefault(fp, {}).update(meta)
            channels_used.append("graph")

    # Fuse with RRF
    total_candidates = len(metadata)
    fused = _rrf_fuse(ranked_lists, metadata, k=k)

    # Convert to SearchResult objects
    results = [
        SearchResult(
            file_path=r["file_path"],
            title=r["title"],
            score=r["score"],
            snippet=r["snippet"],
            sources=r["sources"],
        )
        for r in fused[:limit]
    ]

    return SearchResponse(
        results=results,
        query=query_text,
        channels_used=channels_used,
        total_candidates=total_candidates,
    )

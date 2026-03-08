"""Document chunking for section-level embeddings.

Splits vault markdown files into semantic chunks based on ## headers
with a fixed-size fallback for unstructured documents.

Pure functions only -- no I/O.  File reading is the caller's responsibility.
"""

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Chunk strategy thresholds
# ---------------------------------------------------------------------------
MIN_WORDS_FOR_CHUNKING = 100   # Files under this are embedded whole
MAX_CHUNK_WORDS = 600          # Split header sections larger than this
FIXED_CHUNK_WORDS = 300        # Window size for fixed-size chunking
FIXED_CHUNK_OVERLAP = 50       # Overlap between fixed-size windows
CHUNK_HEADER_LEVEL = 2         # Split at ## level by default


@dataclass
class Chunk:
    """A single chunk from a vault file."""

    chunk_index: int
    content: str
    section_header: str   # "" for whole-file or fixed-size chunks
    header_level: int     # 0 if no header
    start_line: int
    end_line: int
    word_count: int
    chunk_type: str       # "whole_file", "header_based", "fixed_size"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _count_words(text: str) -> int:
    """Fast word count via split()."""
    return len(text.split())


def _line_number_at(text: str, char_offset: int) -> int:
    """Return the 1-based line number for *char_offset* in *text*."""
    return text[:char_offset].count("\n") + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from content.

    Uses the same regex as ``embedding_store.py`` so chunk boundaries
    align with existing whole-file embeddings.
    """
    return _FRONTMATTER_RE.sub("", content).strip()


def detect_structure(content: str) -> dict:
    """Analyze markdown header structure of *content* (frontmatter already stripped).

    Returns::

        {
            'has_headers': bool,
            'header_count': int,
            'header_level': int,   # minimum header level found (e.g. 2 for ##)
            'avg_section_words': int,
            'total_words': int,
        }
    """
    total_words = _count_words(content)
    matches = list(_HEADER_RE.finditer(content))

    if not matches:
        return {
            "has_headers": False,
            "header_count": 0,
            "header_level": 0,
            "avg_section_words": total_words,
            "total_words": total_words,
        }

    min_level = min(len(m.group(1)) for m in matches)

    # Compute average section word count.
    # Sections are text between consecutive headers of the detected level.
    section_starts: list[int] = []
    for m in matches:
        if len(m.group(1)) == min_level:
            section_starts.append(m.start())

    section_word_counts: list[int] = []

    # Content before the first header counts as a section if non-empty.
    preamble = content[: section_starts[0]].strip() if section_starts else ""
    if preamble:
        section_word_counts.append(_count_words(preamble))

    for i, start in enumerate(section_starts):
        end = section_starts[i + 1] if i + 1 < len(section_starts) else len(content)
        section_word_counts.append(_count_words(content[start:end]))

    header_count = len(section_starts)
    avg_section_words = (
        sum(section_word_counts) // len(section_word_counts)
        if section_word_counts
        else total_words
    )

    return {
        "has_headers": True,
        "header_count": header_count,
        "header_level": min_level,
        "avg_section_words": avg_section_words,
        "total_words": total_words,
    }


def chunk_by_headers(
    content: str,
    level: int = CHUNK_HEADER_LEVEL,
) -> list[Chunk]:
    """Split *content* at markdown headers of the given *level*.

    Sections larger than ``MAX_CHUNK_WORDS`` are further split with
    :func:`chunk_fixed_size`.  The first chunk includes any content
    before the first header (the "preamble").

    Returns a list of :class:`Chunk` objects ordered by position.
    """
    pattern = re.compile(rf"^({'#' * level})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))

    if not matches:
        # No headers at the requested level -- fall back to fixed-size.
        return chunk_fixed_size(content)

    # Build (header_text, header_level, section_content, start_char) tuples.
    sections: list[tuple[str, int, str, int]] = []

    # Preamble (text before first header).
    preamble = content[: matches[0].start()].strip()
    if preamble:
        sections.append(("", 0, preamble, 0))

    for i, m in enumerate(matches):
        sec_start = m.start()
        sec_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sec_text = content[sec_start:sec_end].strip()
        sections.append((m.group(2).strip(), level, sec_text, sec_start))

    chunks: list[Chunk] = []
    idx = 0

    for header, hlevel, sec_text, char_off in sections:
        wc = _count_words(sec_text)
        start_ln = _line_number_at(content, char_off)
        end_ln = start_ln + sec_text.count("\n")

        if wc > MAX_CHUNK_WORDS:
            # Sub-split oversized sections.
            sub_chunks = chunk_fixed_size(sec_text)
            for sc in sub_chunks:
                chunks.append(
                    Chunk(
                        chunk_index=idx,
                        content=sc.content,
                        section_header=header,
                        header_level=hlevel,
                        start_line=start_ln + sc.start_line - 1,
                        end_line=start_ln + sc.end_line - 1,
                        word_count=sc.word_count,
                        chunk_type="header_based",
                    )
                )
                idx += 1
        else:
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    content=sec_text,
                    section_header=header,
                    header_level=hlevel,
                    start_line=start_ln,
                    end_line=end_ln,
                    word_count=wc,
                    chunk_type="header_based",
                )
            )
            idx += 1

    return chunks


def chunk_fixed_size(
    content: str,
    window: int = FIXED_CHUNK_WORDS,
    overlap: int = FIXED_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split *content* into overlapping fixed-size word windows.

    Used as the fallback for files without clear header structure.

    Args:
        content: The text to chunk.
        window: Number of words per window.
        overlap: Number of overlapping words between consecutive windows.

    Returns:
        A list of :class:`Chunk` objects with ``chunk_type="fixed_size"``.
    """
    words = content.split()
    total = len(words)

    if total == 0:
        return [
            Chunk(
                chunk_index=0,
                content="",
                section_header="",
                header_level=0,
                start_line=1,
                end_line=1,
                word_count=0,
                chunk_type="fixed_size",
            )
        ]

    step = max(window - overlap, 1)
    chunks: list[Chunk] = []
    idx = 0
    pos = 0

    while pos < total:
        chunk_words = words[pos : pos + window]
        chunk_text = " ".join(chunk_words)
        wc = len(chunk_words)

        # Approximate line numbers from word positions.
        # Count newlines in the original text up to the approximate char offset.
        approx_char_start = len(" ".join(words[:pos])) + (1 if pos > 0 else 0)
        approx_char_end = approx_char_start + len(chunk_text)
        start_ln = _line_number_at(content, min(approx_char_start, len(content) - 1)) if content else 1
        end_ln = _line_number_at(content, min(approx_char_end, len(content) - 1)) if content else 1

        chunks.append(
            Chunk(
                chunk_index=idx,
                content=chunk_text,
                section_header="",
                header_level=0,
                start_line=start_ln,
                end_line=end_ln,
                word_count=wc,
                chunk_type="fixed_size",
            )
        )
        idx += 1
        pos += step

        # Avoid a tiny trailing chunk that would just duplicate the tail.
        if pos < total and (total - pos) < overlap:
            # Include remaining words in the last chunk.
            remaining_text = " ".join(words[pos:])
            last_start = len(" ".join(words[:pos])) + 1
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    content=remaining_text,
                    section_header="",
                    header_level=0,
                    start_line=_line_number_at(content, min(last_start, len(content) - 1)),
                    end_line=_line_number_at(content, len(content) - 1),
                    word_count=len(words[pos:]),
                    chunk_type="fixed_size",
                )
            )
            break

    return chunks


def chunk_file(content: str, file_path: str = "") -> list[Chunk]:
    """Main entry point: analyze and chunk a vault file.

    Decision tree:

    1. Strip frontmatter.
    2. If ``word_count < MIN_WORDS_FOR_CHUNKING``: return a single whole-file chunk.
    3. If the content has clear headers (>= 2): :func:`chunk_by_headers`.
    4. Otherwise: :func:`chunk_fixed_size`.

    Args:
        content: Raw markdown file content (including frontmatter).
        file_path: Optional file path for logging/debugging (not used for I/O).

    Returns:
        A list of :class:`Chunk` objects (always at least 1).
    """
    body = strip_frontmatter(content)

    if not body:
        return [
            Chunk(
                chunk_index=0,
                content="",
                section_header="",
                header_level=0,
                start_line=0,
                end_line=0,
                word_count=0,
                chunk_type="whole_file",
            )
        ]

    words = body.split()
    word_count = len(words)

    if word_count < MIN_WORDS_FOR_CHUNKING:
        return [
            Chunk(
                chunk_index=0,
                content=body,
                section_header="",
                header_level=0,
                start_line=1,
                end_line=body.count("\n") + 1,
                word_count=word_count,
                chunk_type="whole_file",
            )
        ]

    structure = detect_structure(body)

    if structure["has_headers"] and structure["header_count"] >= 2:
        return chunk_by_headers(body, level=structure["header_level"])
    else:
        return chunk_fixed_size(body)

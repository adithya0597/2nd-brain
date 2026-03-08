"""Tests for core.chunker -- document chunking logic."""
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path & module setup (same pattern as test_graph_ops.py)
# ---------------------------------------------------------------------------
BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

from core.chunker import (
    Chunk,
    chunk_by_headers,
    chunk_file,
    chunk_fixed_size,
    detect_structure,
    strip_frontmatter,
    MIN_WORDS_FOR_CHUNKING,
    MAX_CHUNK_WORDS,
    FIXED_CHUNK_WORDS,
    FIXED_CHUNK_OVERLAP,
)


# ===========================================================================
# strip_frontmatter
# ===========================================================================


class TestStripFrontmatter:
    """Tests for YAML frontmatter removal."""

    def test_removes_yaml_frontmatter(self):
        """Standard YAML frontmatter block should be stripped completely."""
        content = "---\ntype: journal\ndate: 2026-03-01\n---\n\nBody text here."
        result = strip_frontmatter(content)
        assert "---" not in result
        assert "type: journal" not in result
        assert "Body text here." in result

    def test_no_frontmatter_returns_content(self):
        """Content without frontmatter should be returned unchanged (stripped)."""
        content = "Just a normal document with no frontmatter."
        result = strip_frontmatter(content)
        assert result == content

    def test_empty_content(self):
        """Empty string should return empty string."""
        result = strip_frontmatter("")
        assert result == ""

    def test_frontmatter_with_complex_yaml(self):
        """Frontmatter with lists, nested values, and special chars."""
        content = (
            "---\n"
            "type: concept\n"
            "icor_elements:\n"
            "  - Fitness\n"
            "  - Nutrition\n"
            "tags: [health, wellness]\n"
            "---\n"
            "\n"
            "# Concept Title\n"
            "\n"
            "Content body."
        )
        result = strip_frontmatter(content)
        assert "icor_elements" not in result
        assert "# Concept Title" in result
        assert "Content body." in result

    def test_frontmatter_only(self):
        """File with only frontmatter and no body."""
        content = "---\ntype: empty\n---\n"
        result = strip_frontmatter(content)
        assert result == ""

    def test_triple_dashes_in_body_not_stripped(self):
        """Triple dashes appearing in the body (not at the start) are preserved."""
        content = "Some preamble.\n\n---\n\nDivider content."
        result = strip_frontmatter(content)
        # The leading triple-dashes must be at position 0 to count as frontmatter
        assert "Some preamble." in result


# ===========================================================================
# detect_structure
# ===========================================================================


class TestDetectStructure:
    """Tests for markdown structure analysis."""

    def test_no_headers(self):
        """Plain text with no headers."""
        content = "Just some text. " * 20
        result = detect_structure(content)
        assert result["has_headers"] is False
        assert result["header_count"] == 0
        assert result["header_level"] == 0
        assert result["total_words"] > 0

    def test_single_header(self):
        """Single ## header detected."""
        content = "## My Section\nSome content here."
        result = detect_structure(content)
        assert result["has_headers"] is True
        assert result["header_count"] == 1
        assert result["header_level"] == 2

    def test_multiple_h2_headers(self):
        """Multiple ## headers correctly counted."""
        content = (
            "## Morning\nWoke up early.\n\n"
            "## Afternoon\nHad lunch.\n\n"
            "## Evening\nWent to sleep."
        )
        result = detect_structure(content)
        assert result["has_headers"] is True
        assert result["header_count"] == 3
        assert result["header_level"] == 2
        assert result["avg_section_words"] > 0

    def test_mixed_header_levels(self):
        """Mixed header levels -- minimum level detected."""
        content = (
            "# Title\n\n"
            "## Section A\nContent A.\n\n"
            "### Subsection A1\nContent A1.\n\n"
            "## Section B\nContent B."
        )
        result = detect_structure(content)
        assert result["has_headers"] is True
        # Minimum level is 1 (the # Title)
        assert result["header_level"] == 1

    def test_h3_only_headers(self):
        """Only ### headers means header_level == 3."""
        content = (
            "### First\nContent first.\n\n"
            "### Second\nContent second."
        )
        result = detect_structure(content)
        assert result["has_headers"] is True
        assert result["header_level"] == 3
        assert result["header_count"] == 2

    def test_preamble_counted_as_section(self):
        """Content before the first header counted as a section for avg calculation."""
        content = (
            "Some preamble text here.\n\n"
            "## Section\n"
            "Section content."
        )
        result = detect_structure(content)
        assert result["has_headers"] is True
        # avg_section_words should account for both preamble and the section
        assert result["avg_section_words"] > 0

    def test_empty_content(self):
        """Empty string returns zero everything."""
        result = detect_structure("")
        assert result["has_headers"] is False
        assert result["header_count"] == 0
        assert result["total_words"] == 0


# ===========================================================================
# chunk_by_headers
# ===========================================================================


class TestChunkByHeaders:
    """Tests for header-based chunking."""

    def test_splits_at_h2(self):
        """## headers should create separate chunks."""
        content = (
            "## Morning\n"
            "Woke up early and had coffee.\n\n"
            "## Afternoon\n"
            "Met with the team for a standup.\n\n"
            "## Evening\n"
            "Read a book before bed."
        )
        chunks = chunk_by_headers(content, level=2)
        assert len(chunks) == 3
        assert all(c.chunk_type == "header_based" for c in chunks)
        headers = [c.section_header for c in chunks]
        assert "Morning" in headers
        assert "Afternoon" in headers
        assert "Evening" in headers

    def test_content_before_first_header(self):
        """Text before the first ## should become a preamble chunk."""
        content = (
            "Some introductory text.\n\n"
            "## Section One\n"
            "Content one.\n\n"
            "## Section Two\n"
            "Content two."
        )
        chunks = chunk_by_headers(content, level=2)
        # Preamble + 2 sections = 3 chunks
        assert len(chunks) == 3
        assert chunks[0].section_header == ""  # preamble has no header
        assert chunks[1].section_header == "Section One"
        assert chunks[2].section_header == "Section Two"

    def test_empty_section(self):
        """Consecutive headers with no content between them still produce chunks."""
        content = (
            "## A\n\n"
            "## B\n"
            "Content B."
        )
        chunks = chunk_by_headers(content, level=2)
        assert len(chunks) == 2
        assert chunks[0].section_header == "A"
        assert chunks[1].section_header == "B"
        assert "Content B" in chunks[1].content

    def test_oversized_section_sub_split(self):
        """Sections exceeding MAX_CHUNK_WORDS get sub-split via fixed-size chunking."""
        # Build a section with more than MAX_CHUNK_WORDS words
        big_section = " ".join(["word"] * (MAX_CHUNK_WORDS + 100))
        content = (
            "## Small Section\n"
            "A small section.\n\n"
            f"## Big Section\n{big_section}"
        )
        chunks = chunk_by_headers(content, level=2)
        # Small section = 1 chunk, big section > 1 chunk
        assert len(chunks) > 2
        # All sub-chunks of the big section should retain the header name
        big_chunks = [c for c in chunks if c.section_header == "Big Section"]
        assert len(big_chunks) >= 2
        assert all(c.chunk_type == "header_based" for c in big_chunks)

    def test_no_matching_headers_falls_back(self):
        """If no headers match the requested level, falls back to fixed-size."""
        content = "### Subsection\nOnly level-3 headers here. " * 20
        # Request level 2 but only level 3 exists
        chunks = chunk_by_headers(content, level=2)
        assert all(c.chunk_type == "fixed_size" for c in chunks)

    def test_chunk_indices_sequential(self):
        """Chunk indices should be 0-based sequential."""
        content = (
            "## A\nContent A.\n\n"
            "## B\nContent B.\n\n"
            "## C\nContent C."
        )
        chunks = chunk_by_headers(content, level=2)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_chunk_preserves_content(self):
        """Chunk content should include the header and body text."""
        content = "## Important\nThis is critical information."
        chunks = chunk_by_headers(content, level=2)
        assert len(chunks) == 1
        assert "## Important" in chunks[0].content
        assert "critical information" in chunks[0].content


# ===========================================================================
# chunk_fixed_size
# ===========================================================================


class TestChunkFixedSize:
    """Tests for fixed-size windowed chunking."""

    def test_basic_windowing(self):
        """Content should be split into window-sized chunks."""
        # Create content with exactly 600 words
        content = " ".join(["word"] * 600)
        chunks = chunk_fixed_size(content, window=300, overlap=0)
        assert len(chunks) == 2
        assert all(c.chunk_type == "fixed_size" for c in chunks)
        assert all(c.word_count == 300 for c in chunks)

    def test_overlap(self):
        """Overlapping windows should share words at boundaries."""
        # 100 distinct words so we can verify overlap
        words = [f"w{i}" for i in range(100)]
        content = " ".join(words)
        chunks = chunk_fixed_size(content, window=60, overlap=20)
        # Window=60, overlap=20, step=40. Positions: 0, 40, 80.
        # But words 80-99 is only 20 words, which is less than overlap (20),
        # so it gets merged into a trailing chunk.
        assert len(chunks) >= 2
        # First chunk words 0-59, second chunk words 40-99
        first_words = set(chunks[0].content.split())
        second_words = set(chunks[1].content.split())
        # Check overlap: words w40-w59 should appear in both
        overlap_words = first_words & second_words
        assert len(overlap_words) > 0

    def test_short_content_single_chunk(self):
        """Content shorter than the window produces a single chunk."""
        content = "Just a few words here."
        chunks = chunk_fixed_size(content, window=300, overlap=50)
        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].word_count == 5

    def test_empty_content_single_chunk(self):
        """Empty content returns a single empty chunk."""
        chunks = chunk_fixed_size("", window=300, overlap=50)
        assert len(chunks) == 1
        assert chunks[0].word_count == 0
        assert chunks[0].content == ""

    def test_indices_sequential(self):
        """Fixed-size chunks get sequential 0-based indices."""
        content = " ".join(["word"] * 900)
        chunks = chunk_fixed_size(content, window=300, overlap=50)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_no_empty_header(self):
        """Fixed-size chunks should have empty section_header."""
        content = " ".join(["hello"] * 200)
        chunks = chunk_fixed_size(content, window=100, overlap=10)
        for c in chunks:
            assert c.section_header == ""
            assert c.header_level == 0

    def test_default_window_and_overlap(self):
        """Default window and overlap values are used."""
        content = " ".join(["word"] * (FIXED_CHUNK_WORDS + 100))
        chunks = chunk_fixed_size(content)
        assert len(chunks) >= 2
        # First chunk should have approximately FIXED_CHUNK_WORDS words
        assert chunks[0].word_count == FIXED_CHUNK_WORDS


# ===========================================================================
# chunk_file (main entry point)
# ===========================================================================


class TestChunkFile:
    """Tests for the main chunk_file orchestrator."""

    def test_short_file_whole_chunk(self):
        """Files under MIN_WORDS_FOR_CHUNKING words get single whole_file chunk."""
        content = "Short note with a few words."
        chunks = chunk_file(content)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "whole_file"

    def test_daily_note_header_based(self):
        """Daily notes with ## headers get header-based chunks.

        Note: chunk_file uses detect_structure which finds the *minimum*
        header level.  A ``# Daily Note`` h1 title would set header_level=1
        with header_count=1, causing a fixed-size fallback.  Real daily
        notes typically have only ## sections (no h1 title), which is the
        pattern we test here.
        """
        # Build content with only ## headers (no #) and enough words to
        # exceed MIN_WORDS_FOR_CHUNKING (100).
        content = """---
type: journal
date: 2026-03-01
---

## Morning Intentions
- Wake up early and go for a run around the neighborhood
- Exercise for 30 minutes at the gym doing strength training
- Read for 20 minutes on distributed systems architecture
- Plan the day ahead and review the backlog items

## Log
Had a productive morning. Started with a 5K run around the neighborhood.
Met with the team to discuss project timelines. The new feature sprint
looks promising. Spent afternoon coding the authentication module.
Had lunch with Sarah to discuss the upcoming conference presentation.
Later in the day I worked on documentation and reviewed pull requests
from the team. Good progress on the backend API refactoring effort.
The evening was quiet, spent time reading about distributed systems
and caching strategies for the next sprint of work ahead.

## Reflections
Today was balanced between physical activity and deep work sessions.
The morning routine is becoming more consistent over the past week.
Need to focus more on the wealth dimension this coming week ahead.
The conference preparation is on track but needs more attention soon.
I should also revisit the quarterly goals to make sure everything
aligns properly with the current sprint work and team expectations.

## Actions
- [ ] Follow up with Sarah on conference details and logistics
- [ ] Review sprint backlog and update the priority rankings
- [ ] Update project timeline with new deadline estimates
- [ ] Research distributed caching strategies for the API layer
- [ ] Schedule dentist appointment for next week sometime
"""
        chunks = chunk_file(content)
        assert len(chunks) >= 3  # At least Morning, Log, Reflections, Actions
        assert all(c.chunk_type == "header_based" for c in chunks)
        # Verify section headers captured
        headers = [c.section_header for c in chunks if c.section_header]
        header_text = " ".join(headers)
        assert "Morning Intentions" in header_text

    def test_no_headers_fixed_size(self):
        """Long files without headers get fixed-size chunks."""
        content = "Word " * 400  # 400 words, no headers
        chunks = chunk_file(content)
        assert len(chunks) >= 2
        assert all(c.chunk_type == "fixed_size" for c in chunks)

    def test_empty_content(self):
        """Empty content returns single empty chunk."""
        chunks = chunk_file("")
        assert len(chunks) == 1
        assert chunks[0].word_count == 0

    def test_frontmatter_stripped(self):
        """Frontmatter is stripped before chunking."""
        content = "---\ntype: journal\n---\n\nShort content."
        chunks = chunk_file(content)
        assert "---" not in chunks[0].content

    def test_chunk_indices_sequential(self):
        """Chunk indices are 0-based sequential."""
        content = (
            "## A\nContent A words here and there. " * 10 + "\n"
            "## B\nContent B words here and there. " * 10 + "\n"
            "## C\nContent C words here and there. " * 10
        )
        chunks = chunk_file(content)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_frontmatter_only_file(self):
        """File with only frontmatter returns single empty whole_file chunk."""
        content = "---\ntype: journal\ndate: 2026-03-01\n---\n"
        chunks = chunk_file(content)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "whole_file"
        assert chunks[0].word_count == 0

    def test_file_just_under_threshold(self):
        """File with exactly MIN_WORDS_FOR_CHUNKING - 1 words gets whole_file."""
        words = " ".join(["word"] * (MIN_WORDS_FOR_CHUNKING - 1))
        chunks = chunk_file(words)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "whole_file"

    def test_file_at_threshold_with_headers(self):
        """File at threshold with headers uses header-based chunking."""
        # Build content at or above the threshold with multiple headers
        section = " ".join(["word"] * 40)
        content = "\n".join([f"## Section {i}\n{section}" for i in range(5)])
        # 5 sections * ~40 words = ~200 words > MIN_WORDS_FOR_CHUNKING
        chunks = chunk_file(content)
        assert all(c.chunk_type == "header_based" for c in chunks)

    def test_file_at_threshold_single_header_uses_fixed(self):
        """File at threshold with only 1 header falls through to fixed-size.

        chunk_file checks ``header_count >= 2`` before choosing header_based.
        """
        content = "## Only Header\n" + " ".join(["word"] * 200)
        chunks = chunk_file(content)
        # Only 1 header, so it should fall through to fixed-size
        assert all(c.chunk_type == "fixed_size" for c in chunks)

    def test_chunk_dataclass_fields(self):
        """Verify all expected fields exist on Chunk objects."""
        chunks = chunk_file("Hello world.")
        c = chunks[0]
        assert hasattr(c, "chunk_index")
        assert hasattr(c, "content")
        assert hasattr(c, "section_header")
        assert hasattr(c, "header_level")
        assert hasattr(c, "start_line")
        assert hasattr(c, "end_line")
        assert hasattr(c, "word_count")
        assert hasattr(c, "chunk_type")

    def test_file_path_parameter_accepted(self):
        """file_path parameter is accepted without error (used for logging)."""
        chunks = chunk_file("Short note.", file_path="Concepts/Test.md")
        assert len(chunks) == 1

    def test_always_returns_at_least_one_chunk(self):
        """No matter what input, at least one chunk is returned."""
        for content in ["", "x", "---\nfoo: bar\n---\n", " ".join(["w"] * 1000)]:
            chunks = chunk_file(content)
            assert len(chunks) >= 1


# ===========================================================================
# Chunk dataclass
# ===========================================================================


class TestChunkDataclass:
    """Tests for the Chunk dataclass itself."""

    def test_chunk_creation(self):
        chunk = Chunk(
            chunk_index=0,
            content="Hello world",
            section_header="Intro",
            header_level=2,
            start_line=1,
            end_line=5,
            word_count=2,
            chunk_type="header_based",
        )
        assert chunk.chunk_index == 0
        assert chunk.content == "Hello world"
        assert chunk.section_header == "Intro"
        assert chunk.header_level == 2
        assert chunk.chunk_type == "header_based"

    def test_chunk_equality(self):
        """Dataclass equality based on fields."""
        a = Chunk(0, "text", "", 0, 1, 1, 1, "whole_file")
        b = Chunk(0, "text", "", 0, 1, 1, 1, "whole_file")
        assert a == b

    def test_chunk_inequality(self):
        a = Chunk(0, "text", "", 0, 1, 1, 1, "whole_file")
        b = Chunk(1, "text", "", 0, 1, 1, 1, "whole_file")
        assert a != b

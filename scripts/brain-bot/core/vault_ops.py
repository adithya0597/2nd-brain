"""Vault file read/write operations."""
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# RLock to serialize vault write operations (reentrant for nested calls like
# create_report_file -> append_to_daily_note)
_vault_lock = threading.RLock()


def _on_vault_write(file_path: Path):
    """Post-write hook: incrementally update vault_index and FTS5 for this file.

    This is the event-driven graph update strategy (inspired by FEA's
    "new content connects instantly" principle). Instead of a file watcher
    daemon, every vault write function calls this hook after writing.

    Runs in a background thread to avoid slowing down the write operation.
    Errors are logged but never propagated — indexing failures should not
    break vault writes.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    def _do_index():
        try:
            from core.vault_indexer import index_single_file
            index_single_file(file_path)
        except Exception:
            logger.debug("Incremental vault index failed for %s", file_path, exc_info=True)

        try:
            from core.fts_index import update_single_file_fts
            update_single_file_fts(file_path)
        except Exception:
            logger.debug("Incremental FTS update failed for %s", file_path, exc_info=True)

        try:
            from core.embedding_store import embed_single_file
            embed_single_file(file_path)
        except Exception:
            logger.debug("Incremental embedding failed for %s", file_path, exc_info=True)

        try:
            from core.chunk_embedder import rechunk_and_embed_file
            rechunk_and_embed_file(file_path, vault_path=config.VAULT_PATH, db_path=config.DB_PATH)
        except Exception:
            logger.debug("Chunk embedding failed for %s", file_path, exc_info=True)

        try:
            from core.icor_affinity import update_icor_edges_for_file
            update_icor_edges_for_file(str(file_path.relative_to(config.VAULT_PATH)))
        except Exception:
            logger.debug("Incremental ICOR affinity failed for %s", file_path, exc_info=True)

        try:
            from core.graph_ops import update_tag_shared_edges_for_file
            update_tag_shared_edges_for_file(str(file_path.relative_to(config.VAULT_PATH)))
        except Exception:
            logger.debug("Incremental tag_shared edges failed for %s", file_path, exc_info=True)

        try:
            from core.graph_ops import update_semantic_similarity_edges_for_file
            update_semantic_similarity_edges_for_file(str(file_path.relative_to(config.VAULT_PATH)))
        except Exception:
            logger.debug("Incremental semantic_similarity edges failed for %s", file_path, exc_info=True)

        try:
            from core.graph_cache import invalidate as _invalidate_graph_cache
            _invalidate_graph_cache()
        except ImportError:
            pass

    threading.Thread(target=_do_index, daemon=True).start()


def read_file(path: Path) -> str:
    """Safely read a file, returning empty string on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return ""
    except Exception as e:
        logger.error("Error reading %s: %s", path, e)
        return ""


def get_daily_note_path(date: str = None) -> Path:
    """Return the path for a daily note. Defaults to today."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return config.VAULT_PATH / "Daily Notes" / f"{date}.md"


def ensure_daily_note(date: str = None) -> Path:
    """Create today's daily note from template if it doesn't exist.

    Returns the path to the daily note.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    path = get_daily_note_path(date)
    if path.exists():
        return path

    with _vault_lock:
        # Double-check after acquiring lock
        if path.exists():
            return path

        # Read template
        template_path = config.VAULT_PATH / "Templates" / "Daily Note.md"
        template = read_file(template_path)
        if not template:
            logger.error("Daily note template not found at %s", template_path)
            return path

        # Replace template variables
        dt = datetime.strptime(date, "%Y-%m-%d")
        full_date = dt.strftime("%A, %B %-d, %Y")
        content = template.replace("{{date:YYYY-MM-DD}}", date)
        content = content.replace("{{date:dddd, MMMM D, YYYY}}", full_date)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Created daily note: %s", path)
        _on_vault_write(path)
        return path


def append_to_daily_note(date: str, content: str, section: str = None) -> bool:
    """Append content to a daily note, optionally under a specific section.

    Args:
        date: Date string in YYYY-MM-DD format.
        content: Markdown content to append.
        section: Optional section header (e.g. "## Log") to insert under.
                 If None, appends to the end of the file.

    Returns:
        True if successful, False otherwise.
    """
    path = ensure_daily_note(date)

    with _vault_lock:
        try:
            existing = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error("Daily note not found after ensure: %s", path)
            return False

        if section:
            # Find the section and insert content after its header line
            lines = existing.split("\n")
            insert_idx = None
            for i, line in enumerate(lines):
                if line.strip().startswith(section):
                    insert_idx = i + 1
                    break

            if insert_idx is not None:
                lines.insert(insert_idx, content)
                path.write_text("\n".join(lines), encoding="utf-8")
            else:
                # Section not found; append to end
                logger.warning("Section '%s' not found in %s, appending to end", section, path)
                path.write_text(existing.rstrip() + "\n\n" + content + "\n", encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n\n" + content + "\n", encoding="utf-8")

        logger.info("Appended to daily note %s (section=%s)", path, section)
        _on_vault_write(path)
        return True


def _format_dimension_links(dimensions: list[str]) -> str:
    """Format dimension names as Obsidian wikilinks."""
    if not dimensions:
        return "Uncategorized"
    return ", ".join(f"[[{dim}]]" for dim in dimensions)


def format_capture_line(
    text: str,
    dimensions: list[str] | None = None,
    is_action: bool = False,
) -> str:
    """Format a capture for daily note append with wikilinks.

    Args:
        text: The captured message text.
        dimensions: List of dimension names (may be empty/None).
        is_action: Whether this is an action item.

    Returns:
        Formatted markdown line(s).
    """
    dim_links = _format_dimension_links(dimensions or [])

    lines = []
    # Main capture line
    lines.append(f"- **[Capture]** {text} _(routed to {dim_links})_ #capture")

    # Action item checkbox if applicable
    if is_action:
        primary = f"[[{dimensions[0]}]]" if dimensions else ""
        dim_tag = f" ({primary})" if primary else ""
        lines.append(f"- [ ] **[Action]** {text}{dim_tag} #action")

    return "\n".join(lines)


def create_inbox_entry(
    content: str,
    source: str = "slack",
    dimensions: list[str] | None = None,
    confidence: float = 0.0,
    method: str = "none",
) -> Path:
    """Create a new file in vault/Inbox/.

    Args:
        content: The raw capture text.
        source: Where the capture came from (default "slack").
        dimensions: Matched dimension names (may be empty/None).
        confidence: Classification confidence score.
        method: Classification method used ("keyword", "embedding", "llm", "none").

    Returns:
        Path to the created file.
    """
    with _vault_lock:
        inbox_dir = config.VAULT_PATH / "Inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now()
        # Use microseconds to avoid filename collisions on rapid captures
        filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{timestamp.microsecond:06d}-{source}.md"
        path = inbox_dir / filename

        dims = dimensions or []
        dim_links = _format_dimension_links(dims)
        # Build frontmatter
        icor_line = f"icor_dimensions: [{', '.join(dims)}]" if dims else "icor_dimensions: []"
        status = "unprocessed" if not dims else "routed"

        frontmatter = f"""---
type: inbox
date: {timestamp.strftime('%Y-%m-%d')}
source: {source}
status: {status}
{icor_line}
confidence: {confidence}
classification_method: {method}
---

"""
        # Body with wikilinks to dimensions
        body = content
        if dims:
            body += f"\n\n**Dimensions:** {dim_links}"

        path.write_text(frontmatter + body + "\n", encoding="utf-8")
        logger.info("Created inbox entry: %s (dims=%s, method=%s)", path, dims, method)
        _on_vault_write(path)
        return path


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Strip path traversal components
    sanitized = name.replace("..", "").replace("/", "-").replace("\\", "-").replace(":", "-")
    sanitized = sanitized.replace('"', "").replace("'", "").replace("?", "")
    sanitized = sanitized.replace("<", "").replace(">", "").replace("|", "")
    # Collapse multiple hyphens/spaces
    import re
    sanitized = re.sub(r"[-\s]+", "-", sanitized).strip("-")
    return sanitized or "untitled"


def _guard_vault_path(file_path: Path) -> None:
    """Raise ValueError if path escapes the vault directory."""
    resolved = file_path.resolve()
    if not resolved.is_relative_to(config.VAULT_PATH.resolve()):
        raise ValueError(f"Path traversal blocked: {file_path} escapes vault")


def create_report_file(
    command: str,
    content: str,
    dimensions: list[str] | None = None,
    date: str | None = None,
) -> Path:
    """Create a report file in vault/Reports/ with proper frontmatter.

    Args:
        command: The brain command that generated this report.
        content: The report content (markdown).
        dimensions: Related ICOR dimensions for wikilinks.
        date: Date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Path to the created file.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    with _vault_lock:
        reports_dir = config.VAULT_PATH / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{date}-{command}.md"
        path = reports_dir / filename
        _guard_vault_path(path)

        dims = dimensions or []
        dim_links = ", ".join(f"[[{d}]]" for d in dims) if dims else ""
        icor_line = f"icor_dimensions: [{', '.join(dims)}]" if dims else "icor_dimensions: []"

        frontmatter = f"""---
type: report
command: {command}
date: {date}
{icor_line}
---

"""
        body = f"# /{command} Report — {date}\n\n"
        if dim_links:
            body += f"**Dimensions:** {dim_links}\n\n"
        body += content

        path.write_text(frontmatter + body + "\n", encoding="utf-8")
        logger.info("Created report: %s", path)
        _on_vault_write(path)

        # Add reference to daily note
        append_to_daily_note(
            date,
            f"- Ran [[Reports/{date}-{command}|/brain:{command}]]",
            section="## Log",
        )

        return path


def create_concept_file(
    name: str,
    summary: str,
    source_notes: list[str] | None = None,
    icor_elements: list[str] | None = None,
    status: str = "seedling",
) -> Path:
    """Create a concept file in vault/Concepts/ with frontmatter and backlinks.

    Args:
        name: Concept name (becomes the filename and title).
        summary: Description/summary of the concept.
        source_notes: List of source daily note dates or file names for backlinks.
        icor_elements: Related ICOR dimensions.
        status: Concept status (seedling, growing, evergreen).

    Returns:
        Path to the created file.
    """
    with _vault_lock:
        concepts_dir = config.VAULT_PATH / "Concepts"
        concepts_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{_sanitize_filename(name)}.md"
        path = concepts_dir / filename
        _guard_vault_path(path)

        elements = icor_elements or []
        sources = source_notes or []
        date = datetime.now().strftime("%Y-%m-%d")

        icor_line = f"icor_elements: [{', '.join(elements)}]" if elements else "icor_elements: []"

        frontmatter = f"""---
type: concept
status: {status}
date: {date}
{icor_line}
---

"""
        body = f"# {name}\n\n{summary}\n"

        if elements:
            dim_links = ", ".join(f"[[{e}]]" for e in elements)
            body += f"\n**Related Dimensions:** {dim_links}\n"

        if sources:
            body += "\n## Sources\n"
            for src in sources:
                body += f"- [[{src}]]\n"

        path.write_text(frontmatter + body, encoding="utf-8")
        logger.info("Created concept: %s", path)
        _on_vault_write(path)
        return path


def create_weekly_plan(
    content: str,
    date: str | None = None,
) -> Path:
    """Create a weekly plan file in vault/Projects/."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    with _vault_lock:
        projects_dir = config.VAULT_PATH / "Projects"
        projects_dir.mkdir(parents=True, exist_ok=True)

        filename = f"Weekly-Plan-{date}.md"
        path = projects_dir / filename
        _guard_vault_path(path)

        frontmatter = f"""---
type: weekly-plan
date: {date}
---

"""
        body = f"# Weekly Plan — {date}\n\n{content}\n"

        path.write_text(frontmatter + body, encoding="utf-8")
        logger.info("Created weekly plan: %s", path)
        _on_vault_write(path)

        # Reference in daily note
        append_to_daily_note(
            date,
            f"- Created [[Projects/{filename}|Weekly Plan]]",
            section="## Log",
        )

        return path


def ensure_dimension_pages():
    """Create dimension index pages in vault/Dimensions/ if they don't exist.

    These are the wikilink targets that make graph connections work.
    """
    dimensions_dir = config.VAULT_PATH / "Dimensions"
    dimensions_dir.mkdir(parents=True, exist_ok=True)

    for dim_name in config.DIMENSION_TOPICS:
        path = dimensions_dir / f"{dim_name}.md"
        if path.exists():
            continue

        frontmatter = f"""---
type: dimension
icor_level: dimension
title: {dim_name}
---

# {dim_name}

This page aggregates all captures, notes, and projects related to **{dim_name}**.

Browse linked notes in the graph view to see connections.
"""
        path.write_text(frontmatter, encoding="utf-8")
        logger.info("Created dimension page: %s", path)


def create_web_clip(
    url: str,
    title: str,
    summary: str,
    icor_elements: list[str] | None = None,
    key_concepts: list[str] | None = None,
    content_preview: str = "",
) -> Path:
    """Create a web clip file in vault/Resources/.

    Returns path to the created file.
    """
    import re as _re

    with _vault_lock:
        resources_dir = config.VAULT_PATH / "Resources"
        resources_dir.mkdir(parents=True, exist_ok=True)

        safe_title = _sanitize_filename(title)[:60]
        date = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date}-{safe_title}.md"
        path = resources_dir / filename
        _guard_vault_path(path)

        # Handle collision
        counter = 1
        while path.exists():
            filename = f"{date}-{safe_title}-{counter}.md"
            path = resources_dir / filename
            counter += 1

        elements = icor_elements or []
        concepts = key_concepts or []
        icor_line = f"icor_elements: [{', '.join(elements)}]" if elements else "icor_elements: []"
        tags_line = f"tags: [{', '.join(concepts)}]" if concepts else "tags: []"

        # Escape quotes in YAML values to prevent malformed frontmatter
        yaml_url = url.replace('"', '\\"')
        yaml_title = title.replace('"', '\\"')

        frontmatter = f"""---
type: web_clip
url: "{yaml_url}"
title: "{yaml_title}"
date: {date}
{icor_line}
{tags_line}
---

"""
        body = f"# {title}\n\n"
        body += f"**Source:** {url}\n\n"

        if summary:
            body += f"## Summary\n\n{summary}\n\n"

        if concepts:
            body += "## Key Concepts\n\n"
            for c in concepts:
                body += f"- {c}\n"
            body += "\n"

        if content_preview:
            body += f"## Content Preview\n\n{content_preview[:2000]}\n"

        path.write_text(frontmatter + body, encoding="utf-8")
        logger.info("Created web clip: %s", path)
        _on_vault_write(path)

        # Reference in daily note
        append_to_daily_note(
            date,
            f"- Saved [[Resources/{filename}|{title}]] from {url}",
            section="## Log",
        )

        return path

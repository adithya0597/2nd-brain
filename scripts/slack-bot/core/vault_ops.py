"""Vault file read/write operations."""
import logging
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)


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
    return True


def create_inbox_entry(content: str, source: str = "slack") -> Path:
    """Create a new file in vault/Inbox/.

    Args:
        content: The raw capture text.
        source: Where the capture came from (default "slack").

    Returns:
        Path to the created file.
    """
    inbox_dir = config.VAULT_PATH / "Inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{source}.md"
    path = inbox_dir / filename

    frontmatter = f"""---
type: inbox
date: {timestamp.strftime('%Y-%m-%d')}
source: {source}
status: unprocessed
---

"""
    path.write_text(frontmatter + content + "\n", encoding="utf-8")
    logger.info("Created inbox entry: %s", path)
    return path

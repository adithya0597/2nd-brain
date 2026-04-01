"""Rolling memo: daily structured append to a single vault file.

Tests whether context compression works before committing to the full
3-tier hierarchical consolidation pipeline. The memo is a real vault file
so the chunker + embedder indexes it automatically via _on_vault_write().
"""
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)

MEMO_PATH = config.VAULT_PATH / "Reports" / "rolling-memo.md"

_FRONTMATTER = """\
---
type: rolling-memo
source: system
date: {date}
tags: [rolling-memo, daily-snapshot]
---

# Rolling Memo

Daily structured snapshots of brain activity. Each entry is a ~200-token
extraction from the day's journal, captures, and engagement data.

"""


def append_to_rolling_memo(content: str, date_str: str | None = None) -> bool:
    """Append a dated memo entry to vault/Reports/rolling-memo.md.

    Creates the file with frontmatter if it doesn't exist.
    Calls _on_vault_write() to trigger indexing (chunker, embedder, FTS5).

    Args:
        content: The memo text to append (should be ~200 tokens).
        date_str: ISO date string (defaults to today).

    Returns:
        True if append succeeded, False on error.
    """
    from core.vault_ops import _vault_lock, _on_vault_write

    date_str = date_str or datetime.now().strftime("%Y-%m-%d")

    try:
        with _vault_lock:
            # Create file with frontmatter if it doesn't exist
            if not MEMO_PATH.exists():
                MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
                MEMO_PATH.write_text(
                    _FRONTMATTER.format(date=date_str) + content.strip() + "\n"
                )
                logger.info("Created rolling memo: %s", MEMO_PATH)
            else:
                # Dedup: skip if today's date already has an entry
                existing = MEMO_PATH.read_text()
                if f"### {date_str}" in existing:
                    logger.info("Rolling memo already has entry for %s, skipping", date_str)
                    return True
                # Append with a blank line separator
                with open(MEMO_PATH, "a") as f:
                    f.write("\n" + content.strip() + "\n")
                logger.info("Appended to rolling memo: %s", date_str)

        # Trigger indexing (FTS5, embeddings, chunks, graph)
        _on_vault_write(MEMO_PATH)
        return True

    except Exception:
        logger.exception("Failed to append rolling memo")
        return False

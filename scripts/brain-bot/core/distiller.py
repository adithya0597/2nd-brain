"""Conversation distiller — extracts atomic vault notes from Claude sessions.

Uses the existing capture pipeline: batch mode, quality gate, provenance
tracking, and inbox entry creation (all shipped in Phase A).
"""
import json
import logging
from pathlib import Path

import config
from core.ai_client import get_ai_client
from core.quality_gate import validate_vault_write
from core.session_parser import find_session_files, parse_session, should_distill
from core.vault_ops import create_inbox_entry, enter_batch_mode, exit_batch_mode
from core.vault_safety import snapshot_vault_before_batch

logger = logging.getLogger(__name__)

DISTILL_PROMPT = """Extract 3-5 atomic knowledge notes from this Claude conversation transcript.

Each note should be a standalone insight, decision, pattern, or explanation that would be useful to recall later. Focus on:
- Architectural decisions and their reasoning
- Bug fixes and root causes
- Patterns, techniques, or approaches learned
- Key facts or configurations discovered

For each note, return a JSON object with:
- title: Short descriptive title (3-8 words)
- content: 2-5 sentences capturing the insight
- category: One of: decision, bugfix, pattern, explanation, configuration
- related_topics: List of 1-3 related topic keywords

Return a JSON array of notes. Example:
[{{"title": "WAL mode prevents read locks", "content": "SQLite WAL mode allows concurrent readers...", "category": "explanation", "related_topics": ["sqlite", "concurrency"]}}]

Transcript (truncated to 8000 chars):
{text}"""


async def distill_session(session_path: Path, session_id: str) -> list[dict]:
    """Extract atomic notes from a single Claude session."""
    texts = list(parse_session(session_path))
    combined = "\n\n".join(texts)[:8000]
    if len(combined) < 200:
        return []

    ai = get_ai_client()
    if ai is None:
        logger.warning("No AI client available for distillation")
        return []

    response = await ai.messages.create(
        model=config.CLASSIFIER_LLM_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": DISTILL_PROMPT.format(text=combined)}],
    )
    raw = response.content[0].text
    try:
        if raw.strip().startswith("```"):
            raw = raw.strip().split("\n", 1)[1].rsplit("```", 1)[0]
        notes = json.loads(raw)
        if not isinstance(notes, list):
            return []
        return notes[:5]
    except (json.JSONDecodeError, IndexError):
        logger.warning("Failed to parse distill response for %s", session_id)
        return []


async def distill_sessions(db_execute, limit: int = 5) -> tuple[int, int]:
    """Distill undistilled sessions. Returns (sessions_processed, notes_created)."""
    from core.db_ops import query

    rows = await query("SELECT session_path FROM distill_log")
    distilled = {r["session_path"] for r in rows}

    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return 0, 0
    candidates = find_session_files(base)
    undistilled = [
        p for p in candidates if str(p) not in distilled and should_distill(p)
    ][:limit]

    if not undistilled:
        return 0, 0

    snapshot_vault_before_batch("distill")
    enter_batch_mode()
    total_notes = 0
    sessions_done = 0

    try:
        for session_path in undistilled:
            session_id = session_path.stem
            notes = await distill_session(session_path, session_id)

            for note in notes:
                content = f"# {note.get('title', 'Untitled')}\n\n"
                content += note.get("content", "")
                if note.get("related_topics"):
                    content += "\n\nRelated: " + ", ".join(
                        f"[[{t}]]" for t in note["related_topics"]
                    )

                issues = validate_vault_write(
                    content, config.VAULT_PATH / "Inbox" / "temp.md"
                )
                if issues:
                    logger.warning(
                        "Quality gate rejected note '%s': %s",
                        note.get("title"),
                        issues,
                    )
                    continue

                create_inbox_entry(
                    content=content,
                    source="distiller",
                    source_session=session_id,
                )
                total_notes += 1

            await db_execute(
                "INSERT OR IGNORE INTO distill_log "
                "(session_path, session_id, note_count, status) "
                "VALUES (?, ?, ?, 'complete')",
                (str(session_path), session_id, len(notes)),
            )
            sessions_done += 1
    finally:
        exit_batch_mode()

    return sessions_done, total_notes

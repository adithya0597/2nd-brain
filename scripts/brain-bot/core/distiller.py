"""Conversation distiller — extracts atomic vault notes from Claude sessions.

Uses the primary AI client (Gemini Flash 2.5 by default) with batch processing
and parallel execution for efficient distillation of large conversation corpora.
"""
import asyncio
import json
import logging
from pathlib import Path

import config
from core.ai_client import get_ai_client
from core.quality_gate import validate_vault_write
from core.session_parser import (
    find_markdown_session_files,
    find_session_files,
    parse_any_session,
    parse_json_export,
    should_distill,
)
from core.vault_ops import create_inbox_entry, enter_batch_mode, exit_batch_mode
from core.vault_safety import snapshot_vault_before_batch

logger = logging.getLogger(__name__)

# Batch processing constants
_CHARS_PER_CONV = 8000
_BATCH_CHAR_LIMIT = 80_000
_MAX_WORKERS = 1  # Sequential to avoid burning free-tier quota (20 req/day)
_MAX_RETRIES = 3

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

BATCH_DISTILL_PROMPT = """Extract 3-5 atomic knowledge notes from EACH of the following Claude conversation transcripts.

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

Return a JSON object where each key is the session ID and each value is an array of notes.
If a conversation has no extractable insights, use an empty array.

Example:
{{"session-abc": [{{"title": "WAL mode prevents read locks", "content": "SQLite WAL mode allows concurrent readers...", "category": "explanation", "related_topics": ["sqlite", "concurrency"]}}], "session-xyz": []}}

{conversations}"""


def _parse_notes_json(raw: str):
    """Parse JSON from LLM response, handling markdown code fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, IndexError):
        return None


async def distill_text(combined: str, session_id: str) -> list[dict]:
    """Extract atomic notes from pre-joined assistant text."""
    if len(combined) < 200:
        return []

    ai = get_ai_client()
    if ai is None:
        logger.warning("No AI client available for distillation")
        return []

    response = await ai.messages.create(
        max_tokens=2000,
        messages=[{"role": "user", "content": DISTILL_PROMPT.format(text=combined[:_CHARS_PER_CONV])}],
    )
    raw = response.content[0].text
    notes = _parse_notes_json(raw)
    if not isinstance(notes, list):
        logger.warning("Failed to parse distill response for %s", session_id)
        return []
    return notes[:5]


async def distill_session(session_path: Path, session_id: str) -> list[dict]:
    """Extract atomic notes from a single Claude session file."""
    texts = list(parse_any_session(session_path))
    combined = "\n\n".join(texts)
    return await distill_text(combined, session_id)


def _build_batches(
    items: list[tuple[str, str]],
    batch_char_limit: int = _BATCH_CHAR_LIMIT,
) -> list[list[tuple[str, str]]]:
    """Group (session_id, text) tuples into batches by total character count."""
    batches: list[list[tuple[str, str]]] = []
    current_batch: list[tuple[str, str]] = []
    current_size = 0

    for session_id, text in items:
        truncated = text[:_CHARS_PER_CONV]
        item_size = len(truncated)
        if current_batch and current_size + item_size > batch_char_limit:
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append((session_id, truncated))
        current_size += item_size

    if current_batch:
        batches.append(current_batch)
    return batches


async def _distill_batch(
    batch: list[tuple[str, str]], ai,
) -> dict[str, list[dict]]:
    """Send a batch of conversations to the LLM. Returns {session_id: [notes]}.

    Retries on rate-limit errors with exponential backoff.
    """
    parts = []
    for session_id, text in batch:
        parts.append(f"--- SESSION: {session_id} ---\n{text}")
    conversations_text = "\n\n".join(parts)

    prompt = BATCH_DISTILL_PROMPT.format(conversations=conversations_text)

    for attempt in range(_MAX_RETRIES):
        try:
            response = await ai.messages.create(
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            parsed = _parse_notes_json(raw)

            if isinstance(parsed, dict):
                return {
                    sid: notes[:5]
                    for sid, notes in parsed.items()
                    if isinstance(notes, list)
                }
            if isinstance(parsed, list) and len(batch) == 1:
                # Single-item batch may return a plain array
                return {batch[0][0]: parsed[:5]}

            # Gemini sometimes returns a flat list even for multi-conv batches
            if isinstance(parsed, list):
                # Best-effort: assign all notes to first session
                return {batch[0][0]: parsed[:5]}

            logger.warning(
                "Unexpected distill response format (type=%s) for batch of %d",
                type(parsed).__name__, len(batch),
            )
            return {}

        except Exception as e:
            err_str = str(e).lower()
            if "resource_exhausted" in err_str or "429" in err_str or "rate" in err_str:
                wait = 2 ** (attempt + 1) * 10  # 20s, 40s, 80s
                logger.warning(
                    "Rate limited, retry in %ds (%d/%d)",
                    wait, attempt + 1, _MAX_RETRIES,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("Distill batch failed: %s", e)
                return {}

    logger.error("Exhausted retries for distill batch")
    return {}


async def _write_notes(notes: list[dict], session_id: str) -> int:
    """Write distilled notes to vault. Returns count of notes written."""
    written = 0
    for note in notes:
        content = f"# {note.get('title', 'Untitled')}\n\n"
        content += note.get("content", "")
        if note.get("related_topics"):
            content += "\n\nRelated: " + ", ".join(
                f"[[{t}]]" for t in note["related_topics"]
            )

        # Validate only the note body (not Related: wikilinks, which are new topics)
        body_for_validation = content.split("\n\nRelated:")[0] if "\n\nRelated:" in content else content
        issues = validate_vault_write(
            body_for_validation, config.VAULT_PATH / "Inbox" / "temp.md"
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
        written += 1
    return written


async def distill_sessions(db_execute, limit: int = 50) -> tuple[int, int]:
    """Distill undistilled sessions with batch processing and parallel execution.

    Packs ~10 conversations per API call (leveraging Gemini's 1M context window),
    then runs batches concurrently. Returns (sessions_processed, notes_created).
    """
    from core.db_ops import query

    rows = await query("SELECT session_path FROM distill_log")
    distilled = {r["session_path"] for r in rows}

    # Collect candidates as (session_id, combined_text, log_key) triples
    candidates: list[tuple[str, str, str]] = []

    # JSONL sessions from ~/.claude/projects/
    jsonl_base = Path.home() / ".claude" / "projects"
    if jsonl_base.exists():
        for p in find_session_files(jsonl_base):
            if len(candidates) >= limit:
                break
            if str(p) in distilled or not should_distill(p):
                continue
            texts = list(parse_any_session(p))
            combined = "\n\n".join(texts)
            if len(combined) >= 200:
                candidates.append((p.stem, combined, str(p)))

    # Markdown sessions from CONVERSATIONS_PATH
    if len(candidates) < limit and config.CONVERSATIONS_PATH.exists():
        for p in find_markdown_session_files(config.CONVERSATIONS_PATH):
            if len(candidates) >= limit:
                break
            if str(p) in distilled or not should_distill(p):
                continue
            texts = list(parse_any_session(p))
            combined = "\n\n".join(texts)
            if len(combined) >= 200:
                candidates.append((p.stem, combined, str(p)))

    # JSON export conversations
    if len(candidates) < limit and config.CONVERSATIONS_PATH.exists():
        for json_file in config.CONVERSATIONS_PATH.glob("**/conversations.json"):
            for conv in parse_json_export(json_file):
                if len(candidates) >= limit:
                    break
                key = f"json:{conv['uuid']}"
                if key in distilled:
                    continue
                combined = "\n\n".join(conv["texts"])
                if len(combined) >= 200:
                    candidates.append((conv["uuid"], combined, key))
            if len(candidates) >= limit:
                break

    if not candidates:
        return 0, 0

    ai = get_ai_client()
    if ai is None:
        logger.warning("No AI client available for distillation")
        return 0, 0

    # Build batches and process in parallel
    items = [(sid, text) for sid, text, _ in candidates]
    batches = _build_batches(items)
    logger.info(
        "Distilling %d sessions in %d batches (%d max workers)",
        len(candidates), len(batches), _MAX_WORKERS,
    )

    sem = asyncio.Semaphore(_MAX_WORKERS)

    async def _process(batch):
        async with sem:
            return await _distill_batch(batch, ai)

    batch_results = await asyncio.gather(*[_process(b) for b in batches])

    # Merge results
    all_notes: dict[str, list[dict]] = {}
    for result in batch_results:
        all_notes.update(result)

    # Write to vault (batch mode wraps only the writes, not the API calls)
    snapshot_vault_before_batch("distill")
    enter_batch_mode()
    total_notes = 0
    sessions_done = 0

    try:
        for session_id, _, log_key in candidates:
            notes = all_notes.get(session_id, [])
            total_notes += await _write_notes(notes, session_id)
            await db_execute(
                "INSERT OR IGNORE INTO distill_log "
                "(session_path, session_id, note_count, status) "
                "VALUES (?, ?, ?, 'complete')",
                (log_key, session_id, len(notes)),
            )
            sessions_done += 1
    finally:
        exit_batch_mode()

    return sessions_done, total_notes

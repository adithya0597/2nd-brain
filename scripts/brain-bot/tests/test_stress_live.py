#!/usr/bin/env python3
"""Live stress test for all Telegram bot commands.

Runs real handlers against real DB/vault/Anthropic API.
Only Telegram I/O is mocked (reply_text, send_message, etc).

Usage:
    cd scripts/brain-bot
    python tests/test_stress_live.py --group A    # AI commands (no input)
    python tests/test_stress_live.py --group B    # AI commands (with input)
    python tests/test_stress_live.py --group C    # Non-AI + special
    python tests/test_stress_live.py              # All groups
"""
import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure brain-bot is on path
BOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)

import config  # noqa: E402 — loads .env, resolves paths
from handlers.commands import (  # noqa: E402
    _handle_cost,
    _handle_find,
    _handle_help,
    _handle_status,
    _handle_sync,
    _run_ai_command,
)
from handlers.dashboard import _handle_dashboard  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)s %(message)s",
)
logger = logging.getLogger("stress_test")

VAULT_PATH = config.VAULT_PATH


# ─── Data Classes ─────────────────────────────────────────────────────

@dataclass
class CommandResult:
    name: str
    group: str
    status: str = "pending"  # pending | pass | fail | skip
    duration_s: float = 0.0
    response_length: int = 0
    response_preview: str = ""
    errors: list = field(default_factory=list)
    vault_file_created: str | None = None
    html_valid: bool = True


# ─── Mock Infrastructure ──────────────────────────────────────────────

class MockTracker:
    """Captures all Telegram output from handlers."""

    def __init__(self):
        self.replies: list[str] = []
        self.sent_messages: list[str] = []
        self.edits: list[str] = []
        self.keyboards = []

    @property
    def all_output(self) -> str:
        return "\n".join(self.replies + self.sent_messages)

    @property
    def total_length(self) -> int:
        return sum(len(t) for t in self.replies + self.sent_messages)


def create_mocks(owner_id: int, args: list[str] | None = None):
    """Create mock Update + Context with output tracking."""
    tracker = MockTracker()

    # Progress message mock (returned by reply_text, supports edit_text/delete)
    progress_msg = AsyncMock()
    progress_msg.edit_text = AsyncMock(
        side_effect=lambda text, **kw: tracker.edits.append(text)
    )
    progress_msg.delete = AsyncMock()

    # Update mock
    update = MagicMock()
    update.effective_user = MagicMock(id=owner_id)
    update.effective_chat = MagicMock(id=owner_id)
    update.message = MagicMock()
    update.message.message_thread_id = None
    update.message.reply_text = AsyncMock(
        side_effect=lambda text, **kw: (tracker.replies.append(text), progress_msg)[1]
    )

    # Context mock with bot
    context = MagicMock()
    context.args = args or []

    async def _mock_send(**kwargs):
        tracker.sent_messages.append(kwargs.get("text", ""))
        if kwargs.get("reply_markup"):
            tracker.keyboards.append(kwargs["reply_markup"])
        return MagicMock(message_id=999)

    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock(side_effect=_mock_send)

    return update, context, tracker


# ─── Validation Helpers ───────────────────────────────────────────────

_TAG_RE = re.compile(r"<(/?)(\w+)(?:\s[^>]*)?>")
_SELF_CLOSING = frozenset({"br", "hr", "img", "input"})


def check_html_balance(text: str) -> list[str]:
    """Return list of unclosed/extra HTML tag issues."""
    issues = []
    stack = []
    for m in _TAG_RE.finditer(text):
        closing, tag = m.group(1) == "/", m.group(2).lower()
        if tag in _SELF_CLOSING:
            continue
        if closing:
            if stack and stack[-1] == tag:
                stack.pop()
        else:
            stack.append(tag)
    for tag in stack:
        issues.append(f"Unclosed <{tag}>")
    return issues


def check_vault_file(brain_cmd: str) -> str | None:
    """Check if expected vault output file exists."""
    today = datetime.now().strftime("%Y-%m-%d")

    if brain_cmd in ("today", "close-day"):
        p = VAULT_PATH / "Daily Notes" / f"{today}.md"
        return str(p) if p.exists() else None

    if brain_cmd == "schedule":
        hits = sorted(VAULT_PATH.glob(f"**/weekly-plan*{today}*"))
        if not hits:
            hits = sorted((VAULT_PATH / "Reports").glob("*schedule*"))
        return str(hits[-1]) if hits else None

    auto_save = {"drift", "emerge", "ideas", "ghost", "challenge", "trace", "connect", "engage", "graduate"}
    if brain_cmd in auto_save:
        reports_dir = VAULT_PATH / "Reports"
        if reports_dir.exists():
            hits = sorted(reports_dir.glob(f"*{brain_cmd}*"))
            return str(hits[-1]) if hits else None

    return None


# ─── Command Specs ────────────────────────────────────────────────────

GROUP_A = [
    {"name": "today",     "type": "ai", "brain_cmd": "today",     "topic": "brain-daily"},
    {"name": "close",     "type": "ai", "brain_cmd": "close-day", "topic": "brain-daily"},
    {"name": "drift",     "type": "ai", "brain_cmd": "drift",     "topic": "brain-insights"},
    {"name": "emerge",    "type": "ai", "brain_cmd": "emerge",    "topic": "brain-insights"},
    {"name": "graduate",  "type": "ai", "brain_cmd": "graduate",  "topic": "brain-insights"},
    {"name": "schedule",  "type": "ai", "brain_cmd": "schedule",  "topic": "brain-daily"},
    {"name": "projects",  "type": "ai", "brain_cmd": "projects",  "topic": "brain-daily"},
    {"name": "resources", "type": "ai", "brain_cmd": "resources", "topic": "brain-daily"},
    {"name": "engage",    "type": "ai", "brain_cmd": "engage",    "topic": "brain-daily"},
]

GROUP_B = [
    {"name": "ghost",     "type": "ai", "brain_cmd": "ghost",     "topic": "brain-insights",
     "args": ["Should", "I", "focus", "on", "health", "this", "month?"]},
    {"name": "trace",     "type": "ai", "brain_cmd": "trace",     "topic": "brain-insights",
     "args": ["personal", "growth"]},
    {"name": "connect",   "type": "ai", "brain_cmd": "connect",   "topic": "brain-insights",
     "args": ['"health"', '"productivity"']},
    {"name": "challenge", "type": "ai", "brain_cmd": "challenge", "topic": "brain-insights",
     "args": ["I", "need", "to", "be", "more", "productive"]},
    {"name": "ideas",     "type": "ai", "brain_cmd": "ideas",     "topic": "brain-insights",
     "args": ["side", "projects"]},
    {"name": "context",   "type": "ai", "brain_cmd": "context-load", "topic": None},
]

GROUP_C = [
    {"name": "status",    "type": "status"},
    {"name": "help",      "type": "help"},
    {"name": "find",      "type": "find_fast", "args": ["mindfulness"]},
    {"name": "find --ai", "type": "find_ai",
     "args": ["--ai", "what", "patterns", "exist", "in", "my", "journal?"]},
    {"name": "dashboard", "type": "dashboard"},
    {"name": "cost",      "type": "cost"},
]

GROUPS = {
    "A": ("Group A: AI commands (no input)", GROUP_A),
    "B": ("Group B: AI commands (with input)", GROUP_B),
    "C": ("Group C: Non-AI + special", GROUP_C),
}


# ─── Execution ────────────────────────────────────────────────────────

async def run_single_command(spec: dict, owner_id: int) -> CommandResult:
    """Run one command, capture output, evaluate."""
    result = CommandResult(name=spec["name"], group=spec.get("group", "?"))
    update, context, tracker = create_mocks(owner_id, spec.get("args"))
    t0 = time.monotonic()

    try:
        match spec["type"]:
            case "ai":
                await _run_ai_command(update, context, spec["brain_cmd"], spec.get("topic"))
            case "status":
                await _handle_status(update, context)
            case "help":
                await _handle_help(update, context)
            case "find_fast" | "find_ai":
                await _handle_find(update, context)
            case "dashboard":
                await _handle_dashboard(update, context)
            case "cost":
                await _handle_cost(update, context)
            case "sync":
                if not config.NOTION_TOKEN:
                    result.status = "skip"
                    result.errors.append("NOTION_TOKEN not set")
                    return result
                await _handle_sync(update, context)
            case other:
                result.status = "fail"
                result.errors.append(f"Unknown type: {other}")
                return result

        result.duration_s = time.monotonic() - t0
        result.response_length = tracker.total_length
        result.response_preview = tracker.all_output[:300] if tracker.all_output else "(empty)"

        # Check for error markers in output
        all_text = tracker.replies + tracker.sent_messages + tracker.edits
        error_texts = [t for t in all_text if "\u274c" in t or "Failed" in t]
        if error_texts:
            result.errors.extend(t[:150] for t in error_texts[:2])

        # HTML balance
        for text in tracker.sent_messages:
            issues = check_html_balance(text)
            if issues:
                result.html_valid = False
                result.errors.append(f"HTML: {issues[:3]}")
                break

        # Minimum response length
        min_len = 200 if spec["type"] == "ai" else 50
        if 0 < result.response_length < min_len:
            result.errors.append(f"Short response ({result.response_length} < {min_len})")

        # Vault file check
        if spec.get("brain_cmd") in {
            "drift", "emerge", "ideas", "ghost", "challenge", "trace",
            "connect", "engage", "today", "close-day", "schedule", "graduate",
        }:
            result.vault_file_created = check_vault_file(spec["brain_cmd"])

        # Final verdict
        if result.errors:
            result.status = "fail"
        elif result.response_length == 0:
            result.status = "fail"
            result.errors.append("No output captured")
        else:
            result.status = "pass"

    except Exception as e:
        result.duration_s = time.monotonic() - t0
        result.status = "fail"
        result.errors.append(f"{type(e).__name__}: {str(e)[:200]}")
        logger.exception("Command /%s failed", spec["name"])

    return result


async def run_group(group_name: str, specs: list[dict], owner_id: int) -> list[CommandResult]:
    """Run all commands in a group sequentially."""
    results = []
    for spec in specs:
        spec["group"] = group_name
        logger.info("--- Running /%s ...", spec["name"])
        r = await run_single_command(spec, owner_id)
        icon = {
            "pass": "\u2705", "fail": "\u274c", "skip": "\u23ed\ufe0f",
        }.get(r.status, "?")
        logger.info(
            "  %s /%s  %s  (%.1fs, %d chars)",
            icon, r.name, r.status, r.duration_s, r.response_length,
        )
        for err in r.errors:
            logger.warning("    -> %s", err[:120])
        results.append(r)
    return results


# ─── Reporting ────────────────────────────────────────────────────────

def print_summary(results: list[CommandResult]):
    print("\n" + "=" * 74)
    print(f"  STRESS TEST RESULTS  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 74)
    print(f"  {'Command':<20} {'Grp':<4} {'Status':<6} {'Time':>7} {'Chars':>7}  Notes")
    print("-" * 74)

    for r in results:
        icon = {"pass": "\u2705", "fail": "\u274c", "skip": "\u23ed"}.get(r.status, "?")
        notes = ""
        if r.vault_file_created:
            notes += "vault "
        if not r.html_valid:
            notes += "html! "
        if r.errors:
            notes += r.errors[0][:35]
        print(
            f"  {icon} {r.name:<18} {r.group:<4} {r.status:<6}"
            f" {r.duration_s:>6.1f}s {r.response_length:>6}  {notes}"
        )

    print("-" * 74)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    total_t = sum(r.duration_s for r in results)
    print(f"  Total: {passed} passed, {failed} failed, {skipped} skipped  ({total_t:.1f}s)")
    print("=" * 74)


async def query_token_cost(since: str) -> dict:
    """Query API cost incurred during the test window."""
    try:
        from core.db_ops import query
        rows = await query(
            "SELECT COALESCE(SUM(cost_estimate_usd),0) AS cost, "
            "COUNT(*) AS calls, "
            "COALESCE(SUM(input_tokens),0) AS inp, "
            "COALESCE(SUM(output_tokens),0) AS out "
            "FROM api_token_logs WHERE created_at >= ?",
            (since,),
        )
        return rows[0] if rows else {}
    except Exception:
        return {}


# ─── Preflight ────────────────────────────────────────────────────────

def preflight():
    ok = True
    checks = [
        ("GEMINI_API_KEY", bool(config.GEMINI_API_KEY)),
        ("Database exists", config.DB_PATH.exists()),
        ("Vault exists", config.VAULT_PATH.exists()),
        ("OWNER_TELEGRAM_ID", bool(config.OWNER_TELEGRAM_ID)),
    ]
    for label, passed in checks:
        icon = "\u2705" if passed else "\u274c"
        print(f"  {icon} {label}")
        if not passed:
            ok = False
    if not ok:
        print("\n  Preflight failed. Check .env and paths.")
        sys.exit(1)
    print()


# ─── Main ─────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Stress test Telegram bot commands")
    parser.add_argument("--group", choices=["A", "B", "C"], help="Run a single group")
    args = parser.parse_args()

    print("\n  Preflight checks:")
    preflight()

    owner_id = config.OWNER_TELEGRAM_ID
    start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_results: list[CommandResult] = []

    if args.group:
        label, specs = GROUPS[args.group]
        logger.info("Starting %s", label)
        all_results.extend(await run_group(args.group, specs, owner_id))
    else:
        for gname in ("A", "B", "C"):
            label, specs = GROUPS[gname]
            logger.info("Starting %s", label)
            all_results.extend(await run_group(gname, specs, owner_id))

    # Summary table
    print_summary(all_results)

    # Token cost
    usage = await query_token_cost(start_ts)
    if usage.get("calls"):
        print(
            f"\n  API: {usage['calls']} calls, "
            f"{usage.get('inp', 0):,} in / {usage.get('out', 0):,} out tokens, "
            f"${usage.get('cost', 0):.4f}"
        )

    # Save JSON
    group_label = args.group or "all"
    out_path = Path(__file__).parent / f"stress_results_{group_label}.json"
    out_path.write_text(json.dumps(
        [
            {
                "name": r.name, "group": r.group, "status": r.status,
                "duration_s": round(r.duration_s, 2),
                "response_length": r.response_length,
                "response_preview": r.response_preview[:500],
                "errors": r.errors, "vault_file": r.vault_file_created,
                "html_valid": r.html_valid,
            }
            for r in all_results
        ],
        indent=2,
    ))
    logger.info("Results -> %s", out_path)

    sys.exit(1 if any(r.status == "fail" for r in all_results) else 0)


if __name__ == "__main__":
    asyncio.run(main())

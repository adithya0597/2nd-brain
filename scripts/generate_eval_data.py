"""Generate synthetic data for evaluation and demo purposes.

Two modes:
  Default: INSERT into brain.db (original eval gate mode)
  --demo:  Create isolated brain_demo.db + vault/Demo/ files

Usage:
    python scripts/generate_eval_data.py                         # eval mode
    python scripts/generate_eval_data.py --demo                  # demo mode
    python scripts/generate_eval_data.py --demo --dry-run        # preview
    python scripts/generate_eval_data.py --demo --date-anchor 2026-04-01
    python scripts/generate_eval_data.py --clean                 # remove demo artifacts
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# --- Configuration ---
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "brain.db"
VAULT_PATH = PROJECT_ROOT / "vault"
DATE_START = datetime(2026, 3, 28)
DATE_END = datetime(2026, 4, 18)
DAYS = 21

random.seed(42)  # Reproducible

# --- Text pools per dimension ---
CAPTURE_TEXTS = {
    "Mind & Growth": [
        "Spent 2 hours on transformer attention mechanisms for the interview prep",
        "Read 3 chapters of Designing Data-Intensive Applications today",
        "Watched Andrej Karpathy's neural net lecture, taking notes on backprop",
        "Completed first 3 LeetCode medium problems on dynamic programming",
        "Deep work session on system design patterns — load balancers and caching",
        "Reviewed spaced repetition research for better concept retention",
        "Studied RAG pipeline architectures — hybrid search seems most promising",
        "Read about graph neural networks and their applications in knowledge systems",
        "Practiced mock interview questions on ML system design",
        "Explored prompt engineering techniques for structured extraction",
        "Finished the embeddings chapter in the NLP textbook",
        "Researched Matryoshka representation learning for dimensionality reduction",
        "Worked through a Kaggle notebook on recommendation systems",
        "Read paper on MAGMA multi-graph memory architecture",
        "Studied vector database indexing strategies HNSW vs IVFFlat",
    ],
    "Health & Vitality": [
        "Morning run 5K followed by stretching. Feeling great.",
        "Meal prepped for the week: chicken rice broccoli",
        "Hit legs today. Squat PR at 225 lbs",
        "Tried a new HIIT routine, 30 min. Intense but effective",
        "Tracked macros today — 180g protein hit the target",
        "Evening yoga session, 20 minutes. Good for recovery",
        "Gym: push day. Bench press 3x8 at 185",
        "Started tracking sleep with the new app. 7.5 hours last night",
        "Cooked a healthy stir-fry instead of ordering out",
        "Morning cold shower experiment day 3 — getting easier",
        "Foam rolled after deadlift session. Hamstrings tight.",
        "Walked 10K steps today without trying. Good day.",
    ],
    "Systems & Environment": [
        "Updated the 2nd brain bot to handle voice captures",
        "Cleaned up workspace, organized cables and desk setup",
        "Automated LinkedIn daily scan with a Python script",
        "Set up Litestream for SQLite backup to S3",
        "Refactored the classifier pipeline for better accuracy",
        "Fixed the Notion sync TOCTOU race condition",
        "Configured launchd for bot auto-restart on crash",
        "Organized vault folder structure — moved stale files to archive",
        "Updated Python dependencies, fixed 3 deprecation warnings",
    ],
    "Wealth & Finance": [
        "Reviewed portfolio allocation, considering more index fund exposure",
        "Researched algorithmic trading backtesting frameworks",
        "Calculated monthly burn rate — need to cut subscriptions",
        "Read about dollar-cost averaging vs lump sum investing",
        "Tracked all expenses this week — eating out is the biggest leak",
        "Looked into tax-advantaged accounts for freelance income",
        "Compared brokerage fees across platforms",
    ],
    "Purpose & Impact": [
        "Had a great conversation about potential AI consulting opportunities",
        "Outlined ideas for an open-source contribution to LangChain",
        "Reflected on career direction — ML engineering vs product",
        "Drafted a blog post outline about building personal knowledge systems",
        "Mentored a junior developer on Python async patterns",
        "Brainstormed ways to combine fashion and AI for the brand project",
    ],
    "Relationships": [
        "Caught up with college friend over dinner, good conversation",
        "Called mom, she's doing well",
        "Coffee chat with a recruiter — interesting lead at a startup",
        "Texted the old roommate, planning a catch-up next week",
        "Lunch with a former colleague — they switched to ML too",
    ],
}

DIMENSIONS = list(CAPTURE_TEXTS.keys())
DIM_WEIGHTS = [0.30, 0.25, 0.18, 0.12, 0.10, 0.05]  # Must match DIMENSIONS order

MOODS = ["great", "good", "okay", "tired", None]
MOOD_WEIGHTS = [0.20, 0.40, 0.25, 0.10, 0.05]
ENERGIES = ["high", "medium", "low", None]
ENERGY_WEIGHTS = [0.25, 0.40, 0.20, 0.15]

SEARCH_QUERIES = [
    "investment strategy", "morning routine", "AI project progress", "workout schedule",
    "transformer architecture", "meal prep ideas", "portfolio allocation", "interview prep",
    "knowledge graph design", "productivity system", "spaced repetition", "career direction",
    "fashion brand ideas", "system design patterns", "vault organization", "weekly planning",
    "embedding models comparison", "gym routine", "Python async patterns", "RAG pipeline",
    "open source contributions", "LinkedIn outreach", "sleep optimization", "budget tracking",
    "concept graduation", "graph memory research", "Notion sync issues", "daily reflection",
    "ML system design interview", "personal brand building",
]

SEARCH_COMMANDS = ["find", "find", "find", "find", "trace", "trace", "ideas", "ideas", "ideas", "connect", "connect", "context"]

# Real file paths from vault
VAULT_FILES = [
    "Dimensions/Mind & Growth.md", "Dimensions/Health & Vitality.md",
    "Dimensions/Systems & Environment.md", "Dimensions/Wealth & Finance.md",
    "Dimensions/Purpose & Impact.md", "Dimensions/Relationships.md",
    "Goals/Investment-Portfolio.md", "Projects/AI-assisted-apparel-Assistant.md",
    "Projects/AI-automated-trader.md", "Projects/Create-a-Portfolio-Agent.md",
    "Projects/Design-Agent.md", "Projects/Ideas-in-Fashion-Industry.md",
    "Projects/Investment-Portfolio.md", "Projects/LinkedIn-Portfolio.md",
    "LinkedIn Portfolio.md", "My-brand.md", "Side-Project-Ideas.md",
    "Reports/2026-03-11-drift.md", "Reports/2026-03-17-maintain.md",
    "Identity/ICOR.md", "Identity/Values.md", "Identity/Active-Projects.md",
]


def gen_dates(n_days=DAYS):
    """Generate date objects for the simulation period."""
    return [DATE_START + timedelta(days=i) for i in range(n_days)]


def gen_captures(dates):
    """Generate ~80 capture rows across 21 days."""
    rows = []
    # Ensure graduation-eligible clusters
    # Mind & Growth: 12+ captures, 8+ distinct days
    # Health & Vitality: 10+ captures, 8+ distinct days
    # Systems: 8+ captures, 7+ distinct days
    # Purpose: 6+ captures, 7+ distinct days
    forced = {
        "Mind & Growth": {"count": 14, "min_days": 9},
        "Health & Vitality": {"count": 11, "min_days": 8},
        "Systems & Environment": {"count": 9, "min_days": 7},
        "Purpose & Impact": {"count": 7, "min_days": 7},
    }

    for dim, spec in forced.items():
        day_indices = sorted(random.sample(range(DAYS), spec["min_days"]))
        extra = spec["count"] - spec["min_days"]
        extra_days = [random.choice(day_indices) for _ in range(extra)]
        all_days = day_indices + extra_days
        for di in all_days:
            dt = dates[di]
            hour = random.choice([8, 9, 10, 14, 15, 20, 21, 22])
            minute = random.randint(0, 59)
            ts = dt.replace(hour=hour, minute=minute)
            text = random.choice(CAPTURE_TEXTS[dim])
            conf = round(random.uniform(0.55, 0.95), 2)
            method = random.choices(["keyword", "embedding", "llm"], [0.6, 0.3, 0.1])[0]
            dims = [dim]
            if random.random() < 0.3:
                secondary = random.choice([d for d in DIMENSIONS if d != dim])
                dims.append(secondary)
            rows.append({
                "message_text": text,
                "dimensions_json": json.dumps(dims),
                "confidence": conf,
                "method": method,
                "is_actionable": 1 if random.random() < 0.3 else 0,
                "source_channel": "brain-inbox",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
            })

    # Add remaining dimensions (lighter)
    for dim in ["Wealth & Finance", "Relationships"]:
        n = random.randint(3, 5)
        day_indices = sorted(random.sample(range(DAYS), min(n, DAYS)))
        for di in day_indices:
            dt = dates[di]
            hour = random.choice([9, 12, 18, 21])
            ts = dt.replace(hour=hour, minute=random.randint(0, 59))
            text = random.choice(CAPTURE_TEXTS[dim])
            dims = [dim]
            rows.append({
                "message_text": text,
                "dimensions_json": json.dumps(dims),
                "confidence": round(random.uniform(0.55, 0.90), 2),
                "method": random.choices(["keyword", "embedding"], [0.7, 0.3])[0],
                "is_actionable": 0,
                "source_channel": "brain-inbox",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
            })

    rows.sort(key=lambda r: r["created_at"])
    return rows


def gen_search_logs(dates):
    """Generate ~65 search_log rows."""
    rows = []
    memo_path = "Reports/rolling-memo.md"
    # Guarantee memo appears in at least 5 distinct commands
    must_have_memo = [
        ("find", 0), ("find", 3), ("trace", 1), ("ideas", 2),
        ("connect", 4), ("context", 5), ("ideas", 6), ("trace", 7),
        ("find", 8), ("connect", 9),
    ]

    for i in range(65):
        dt = dates[i % DAYS]
        hour = random.randint(7, 23)
        ts = dt.replace(hour=hour, minute=random.randint(0, 59))
        query = random.choice(SEARCH_QUERIES)
        cmd = random.choice(SEARCH_COMMANDS)

        # Override command for guaranteed memo entries
        forced_memo = None
        for fc, fi in must_have_memo:
            if fi == i:
                forced_memo = fc
                break
        if forced_memo:
            cmd = forced_memo

        n_per_channel = random.randint(3, 8)
        files = random.sample(VAULT_FILES, min(n_per_channel, len(VAULT_FILES)))

        # Ensure memo appears in guaranteed slots
        include_memo = (forced_memo is not None)
        rankings = {}
        for ch in ["vector", "fts", "graph", "chunks"]:
            ch_files = random.sample(VAULT_FILES, random.randint(2, 6))
            if include_memo and ch in ("vector", "chunks"):
                ch_files.insert(random.randint(0, 2), memo_path)
            rankings[ch] = ch_files

        rrf = list(dict.fromkeys(
            f for ch_list in rankings.values() for f in ch_list
        ))[:10]
        if include_memo and memo_path not in rrf:
            rrf.insert(random.randint(0, 3), memo_path)

        rows.append({
            "query": query,
            "command": cmd,
            "channel_rankings": json.dumps(rankings),
            "rrf_ranking": json.dumps(rrf),
            "channels_used": "vector,fts,graph,chunks",
            "total_candidates": len(rrf) + random.randint(2, 15),
            "result_count": len(rrf),
            "elapsed_ms": round(random.uniform(15.0, 350.0), 2),
            "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
        })

    rows.sort(key=lambda r: r["created_at"])
    return rows


def gen_graduation_proposals(capture_ids_by_dim):
    """Generate 4 proposals: 2 accepted, 1 rejected, 1 snoozed."""
    proposals = []
    specs = [
        ("Mind & Growth Insights", "Mind & Growth", "approved", 5, 7),
        ("Fitness Tracking System", "Health & Vitality", "approved", 7, 10),
        ("Systems Automation", "Systems & Environment", "rejected", 10, 12),
        ("Purpose Alignment", "Purpose & Impact", "snoozed", 14, None),
    ]
    for title, dim, status, prop_day, resolve_day in specs:
        ids = capture_ids_by_dim.get(dim, [])[:6]
        str_ids = [str(i) for i in ids]
        cluster_hash = hashlib.md5("|".join(sorted(str_ids)).encode()).hexdigest()
        proposed_at = (DATE_START + timedelta(days=prop_day)).strftime("%Y-%m-%d 05:15:00")
        resolved_at = (DATE_START + timedelta(days=resolve_day)).strftime("%Y-%m-%d 12:00:00") if resolve_day else None
        snooze_until = (DATE_START + timedelta(days=prop_day + 7)).strftime("%Y-%m-%d") if status == "snoozed" else None

        proposals.append({
            "cluster_hash": cluster_hash,
            "proposed_title": title,
            "proposed_dimension": dim,
            "source_capture_ids": json.dumps(str_ids),
            "source_texts": json.dumps([f"capture {i}" for i in ids[:3]]),
            "status": status,
            "message_id": 5000 + len(proposals),
            "proposed_at": proposed_at,
            "resolved_at": resolved_at,
            "snooze_until": snooze_until,
        })
    return proposals


def gen_journal_entries(dates, captures):
    """Generate ~16 journal entries (not every day)."""
    journal_days = sorted(random.sample(range(DAYS), 16))
    rows = []
    for di in journal_days:
        dt = dates[di]
        date_str = dt.strftime("%Y-%m-%d")
        day_captures = [c for c in captures if c["created_at"].startswith(date_str)]
        dims = set()
        for c in day_captures:
            dims.update(json.loads(c["dimensions_json"]))
        mood = random.choices(MOODS, MOOD_WEIGHTS)[0]
        energy = random.choices(ENERGIES, ENERGY_WEIGHTS)[0]
        content = f"# {dt.strftime('%A, %B %d, %Y')}\n\n## Morning\nStarted the day with focus.\n\n## Log\n"
        for c in day_captures[:3]:
            content += f"- {c['message_text'][:80]}\n"
        content += f"\n## Reflections\nProductive day overall. Touched {len(dims)} dimensions."
        summary = f"Day focused on {', '.join(list(dims)[:3]) or 'general activity'}."
        sentiment = round(random.uniform(0.4, 0.9), 2)

        rows.append({
            "date": date_str,
            "content": content,
            "mood": mood,
            "energy": energy,
            "icor_elements": json.dumps(list(dims)),
            "summary": summary,
            "sentiment_score": sentiment,
            "file_path": f"Daily Notes/{date_str}.md",
        })
    return rows


def gen_engagement(dates, captures, journals):
    """Generate 21 engagement_daily rows."""
    journal_dates = {j["date"] for j in journals}
    rows = []
    for di in range(DAYS):
        dt = dates[di]
        date_str = dt.strftime("%Y-%m-%d")
        day_caps = [c for c in captures if c["created_at"].startswith(date_str)]
        has_journal = date_str in journal_dates
        dims = set()
        for c in day_caps:
            dims.update(json.loads(c["dimensions_json"]))
        dim_mentions = {}
        for c in day_caps:
            for d in json.loads(c["dimensions_json"]):
                dim_mentions[d] = dim_mentions.get(d, 0) + 1

        caps_count = len(day_caps)
        actionable = sum(1 for c in day_caps if c["is_actionable"])
        journal_wc = random.randint(100, 500) if has_journal else 0

        # Simplified engagement formula
        score = min(10.0, (
            (2.0 if has_journal else 0.0) +
            min(caps_count / 5 * 2, 2.0) +
            min(actionable / 3 * 2, 2.0) +
            min(len(dims) / 3 * 2, 2.0) +
            random.uniform(0, 1.0)
        ))

        rows.append({
            "date": date_str,
            "captures_count": caps_count,
            "actionable_captures": actionable,
            "actions_created": actionable,
            "actions_completed": max(0, actionable - random.randint(0, 2)),
            "actions_pending": random.randint(0, 3),
            "journal_entry_count": 1 if has_journal else 0,
            "journal_word_count": journal_wc,
            "avg_sentiment": round(random.uniform(0.4, 0.85), 2),
            "mood": random.choices(MOODS[:4], MOOD_WEIGHTS[:4])[0] if has_journal else None,
            "energy": random.choices(ENERGIES[:3], ENERGY_WEIGHTS[:3])[0] if has_journal else None,
            "dimension_mentions_json": json.dumps(dim_mentions),
            "vault_files_modified": random.randint(0, 3),
            "vault_files_created": random.randint(0, 2),
            "edges_created": random.randint(0, 5),
            "notion_items_synced": random.randint(0, 2),
            "engagement_score": round(score, 1),
        })
    return rows


def gen_vault_edges():
    """Generate ~15 new edges, 12 with verified_at, 3 without."""
    # Pairs of existing nodes that likely don't have edges
    pairs = [
        (1621, 29, "icor_affinity", 0.65),  # Investment-Portfolio -> Wealth
        (1636, 32, "icor_affinity", 0.58),  # LinkedIn Portfolio -> Purpose
        (1637, 31, "icor_affinity", 0.62),  # My-brand -> Mind & Growth
        (1638, 31, "icor_affinity", 0.70),  # AI-apparel -> Mind & Growth
        (1639, 29, "icor_affinity", 0.68),  # AI-trader -> Wealth
        (1640, 31, "icor_affinity", 0.72),  # Portfolio-Agent -> Mind & Growth
        (1641, 28, "icor_affinity", 0.55),  # Denim-Jacket -> Health (stretch)
        (1642, 31, "icor_affinity", 0.74),  # Design-Agent -> Mind & Growth
        (1643, 29, "icor_affinity", 0.60),  # Fashion-Ideas -> Wealth
        (1644, 29, "icor_affinity", 0.66),  # Investment-Porfolio -> Wealth
        (1646, 32, "icor_affinity", 0.59),  # LinkedIn-Portfolio -> Purpose
        (1647, 28, "icor_affinity", 0.53),  # Hoodies -> Health
        (1655, 31, "icor_affinity", 0.64),  # Side-Project-Ideas -> Mind & Growth
        (1655, 33, "icor_affinity", 0.57),  # Side-Project-Ideas -> Systems
        (1637, 32, "icor_affinity", 0.61),  # My-brand -> Purpose
    ]
    rows = []
    for i, (src, tgt, etype, weight) in enumerate(pairs):
        verified = datetime(2026, 3, 28, 10, 0, i).strftime("%Y-%m-%d %H:%M:%S") if i < 12 else None
        rows.append({
            "source_node_id": src,
            "target_node_id": tgt,
            "edge_type": etype,
            "weight": weight,
            "metadata_json": "{}",
            "verified_at": verified,
        })
    return rows


def gen_rolling_memo(dates, captures, journals):
    """Generate rolling-memo.md with daily entries for each date in dates."""
    header = f"""---
type: rolling-memo
source: system
date: {dates[0].strftime('%Y-%m-%d')}
tags: [rolling-memo, daily-snapshot]
---

# Rolling Memo

Daily structured snapshots of brain activity. Each entry is a ~200-token
extraction from the day's journal, captures, and engagement data.

"""
    journal_dates = {j["date"]: j for j in journals}
    entries = []
    for di in range(len(dates)):
        dt = dates[di]
        date_str = dt.strftime("%Y-%m-%d")
        day_caps = [c for c in captures if c["created_at"].startswith(date_str)]
        journal = journal_dates.get(date_str)
        dims = set()
        for c in day_caps:
            dims.update(json.loads(c["dimensions_json"]))

        mood_energy = f"{journal['mood'] or 'unknown'} / {journal['energy'] or 'unknown'}" if journal else "no journal entry"
        icor = ", ".join(sorted(dims)) or "none"
        themes = []
        for c in day_caps[:4]:
            themes.append(f"- {c['message_text'][:60]}")
        if not themes:
            themes = ["- Quiet day, no captures"]
        decisions = "none"
        for c in day_caps:
            if "committed" in c["message_text"].lower() or "decided" in c["message_text"].lower():
                decisions = c["message_text"][:80]
                break

        entry = f"""### {date_str}

**Mood/Energy**: {mood_energy}
**ICOR Active**: {icor}
**Key Themes**:
{chr(10).join(themes)}
**Decisions Made**: {decisions}
**Open Thread**: Balancing depth vs breadth across ICOR dimensions
**Carry Forward**: Continue momentum on strongest dimension
"""
        entries.append(entry)

    return header + "\n".join(entries)


# --- Demo-mode generators (leaf-only seeding) ---

TASK_TEXTS = [
    "Need to call the dentist this week",
    "Follow up with Alex about the project timeline by Friday",
    "Book flight for the conference next month",
    "Submit the quarterly report before Thursday EOD",
    "Pick up dry cleaning before Saturday",
    "Schedule a 1:1 with the manager to discuss promotion path",
    "Renew gym membership before it expires",
    "Set up automatic bill payments for utilities",
]

IDEA_TEXTS = [
    "What if we used embeddings for the search feature instead of keyword matching",
    "Interesting article on spaced repetition — could apply to the learning tracker",
    "Could build a personal CRM that syncs with Telegram contacts",
    "Idea: weekly auto-generated review video from vault activity",
    "What about using graph clustering to auto-suggest concept connections",
]

REFLECTION_TEXTS = [
    "Today's standup went well, team is aligned on the roadmap",
    "Feeling more energized after switching to morning workouts",
    "Realized I've been neglecting the finance dimension for weeks",
    "Good deep work session today, 3 hours uninterrupted on the ML project",
    "Need to be more intentional about relationship touchpoints",
]

UPDATE_TEXTS = [
    "Finished the API integration, moving to testing phase",
    "Ran 5k in 24:30 — new personal best",
    "Completed chapter 7 of the ML textbook",
    "Pushed the classifier accuracy from 82% to 87% today",
    "Organized the vault, archived 20 stale files",
]

INTENTS = ["task", "task", "task", "task", "idea", "idea", "idea",
           "reflection", "reflection", "update", "update", "question"]


def _demo_dates(anchor, n_days=14):
    """Generate T-14 to T-1 relative dates."""
    return [anchor - timedelta(days=n_days - i) for i in range(n_days)]


def gen_demo_captures(dates):
    """Generate ~60 captures weighted by dimension profile for demo mode."""
    all_texts = {**CAPTURE_TEXTS}  # reuse existing pools
    rows = []
    # Dimension weights: Mind=HOT, Health=WARM, Systems=WARM, Wealth=COLD, Purpose=COLD, Relationships=FROZEN
    dim_counts = {
        "Mind & Growth": 18, "Health & Vitality": 12, "Systems & Environment": 10,
        "Wealth & Finance": 5, "Purpose & Impact": 4, "Relationships": 2,
    }
    intent_texts = {"task": TASK_TEXTS, "idea": IDEA_TEXTS,
                    "reflection": REFLECTION_TEXTS, "update": UPDATE_TEXTS}

    for dim, count in dim_counts.items():
        pool = all_texts.get(dim, []) + TASK_TEXTS + IDEA_TEXTS
        for i in range(count):
            dt = random.choice(dates)
            hour = random.choice([7, 8, 9, 10, 12, 14, 16, 18, 20, 21])
            ts = dt.replace(hour=hour, minute=random.randint(0, 59))
            intent = random.choice(INTENTS)
            text = random.choice(intent_texts.get(intent, pool))
            if intent not in intent_texts:
                text = random.choice(pool)
            rows.append({
                "message_text": text,
                "dimensions_json": json.dumps([dim]),
                "confidence": round(random.uniform(0.55, 0.95), 2),
                "method": random.choices(["keyword", "embedding", "llm"], [0.5, 0.35, 0.15])[0],
                "is_actionable": 1 if intent == "task" else 0,
                "source_channel": "brain-inbox",
                "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
            })
    rows.sort(key=lambda r: r["created_at"])
    return rows


def gen_demo_classifications(captures):
    """Generate classifications mirroring captures. ~15% with user corrections."""
    rows = []
    for c in captures:
        dims = json.loads(c["dimensions_json"])
        correction = None
        corrected_at = None
        if random.random() < 0.15:
            other = random.choice([d for d in DIMENSIONS if d != dims[0]])
            correction = other
            corrected_at = c["created_at"]
        rows.append({
            "message_text": c["message_text"],
            "message_ts": c["created_at"],
            "primary_dimension": dims[0],
            "confidence": c["confidence"],
            "method": c["method"],
            "all_scores_json": json.dumps({d: round(random.uniform(0.1, 0.9), 2) for d in DIMENSIONS}),
            "user_correction": correction,
            "corrected_at": corrected_at,
            "created_at": c["created_at"],
        })
    return rows


def gen_demo_action_items(dates, captures):
    """Generate ~25 action items with varied statuses."""
    actionable = [c for c in captures if c["is_actionable"]]
    if len(actionable) < 10:
        actionable = captures[:25]  # fallback
    rows = []
    statuses = (["pending"] * 10 + ["completed"] * 6 + ["in_progress"] * 3 +
                ["delegated"] * 2 + ["cancelled"] * 2)
    random.shuffle(statuses)

    for i, status in enumerate(statuses[:min(25, len(actionable))]):
        c = actionable[i % len(actionable)]
        dt = datetime.strptime(c["created_at"], "%Y-%m-%d %H:%M:%S")
        dims = json.loads(c["dimensions_json"])
        due = None
        completed_at = None
        if status == "pending" and i < 5:
            due = (dt - timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d")  # stale
        elif status == "pending":
            due = (dt + timedelta(days=random.randint(1, 7))).strftime("%Y-%m-%d")
        elif status == "completed":
            completed_at = (dt + timedelta(days=random.randint(1, 3))).strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "description": c["message_text"][:120],
            "source_file": f"Daily Notes/{dt.strftime('%Y-%m-%d')}.md",
            "source_date": dt.strftime("%Y-%m-%d"),
            "status": status,
            "icor_element": dims[0] if dims else None,
            "created_at": c["created_at"],
            "completed_at": completed_at,
            "due_date": due,
        })
    return rows


def gen_demo_reminders(action_items):
    """Generate ~10 reminders linked to pending action items with due dates."""
    pending_with_due = [a for a in action_items if a["status"] == "pending" and a.get("due_date")]
    rows = []
    for a in pending_with_due[:10]:
        remind_at = a["due_date"] + " 13:00:00"  # 7am CST = 13:00 UTC
        rows.append({
            "action_index": action_items.index(a),  # will be replaced with real ID after insert
            "remind_at": remind_at,
            "status": "pending",
            "created_at": a["created_at"],
        })
    return rows


def gen_demo_keyword_feedback():
    """Generate ~30 keyword feedback rows, 5 per dimension."""
    rows = []
    for dim, keywords in {
        "Mind & Growth": ["learn", "study", "research", "book", "course"],
        "Health & Vitality": ["workout", "run", "gym", "sleep", "diet"],
        "Systems & Environment": ["automate", "organize", "setup", "tool", "workflow"],
        "Wealth & Finance": ["invest", "budget", "savings", "portfolio", "expense"],
        "Purpose & Impact": ["career", "mentor", "impact", "volunteer", "mission"],
        "Relationships": ["friend", "family", "catch up", "dinner", "social"],
    }.items():
        for kw in keywords:
            s = random.randint(3, 20)
            rows.append({
                "dimension": dim,
                "keyword": kw,
                "source": random.choice(["seed", "learned"]),
                "success_count": s,
                "fail_count": random.randint(0, max(1, s // 3)),
            })
    return rows


def gen_demo_extraction_feedback(captures):
    """Generate ~15 extraction feedback rows. ~80% correct."""
    rows = []
    sample = random.sample(captures, min(15, len(captures)))
    for c in sample:
        correct = random.random() < 0.8
        rows.append({
            "capture_index": captures.index(c),  # replaced with real ID after insert
            "field_name": random.choice(["intent", "dimension", "project", "due_date"]),
            "proposed_value": random.choice(["task", "idea", "Mind & Growth", "2026-04-01"]),
            "confirmed_value": None if correct else random.choice(["reflection", "Health & Vitality"]),
            "was_correct": 1 if correct else 0,
        })
    return rows


def gen_demo_vault_files(dates, captures, journals):
    """Create ~20 vault files in vault/Demo/."""
    demo_vault = VAULT_PATH / "Demo"
    daily_dir = demo_vault / "Daily Notes"
    concepts_dir = demo_vault / "Concepts"
    reports_dir = demo_vault / "Reports"
    for d in [daily_dir, concepts_dir, reports_dir]:
        d.mkdir(parents=True, exist_ok=True)

    files_created = []

    # 14 daily notes
    for dt in dates:
        date_str = dt.strftime("%Y-%m-%d")
        day_name = dt.strftime("%A, %B %d, %Y")
        day_caps = [c for c in captures if c["created_at"].startswith(date_str)]
        dims = set()
        for c in day_caps:
            dims.update(json.loads(c["dimensions_json"]))
        j = next((j for j in journals if j["date"] == date_str), None)
        mood = j["mood"] if j else random.choices(MOODS[:4], MOOD_WEIGHTS[:4])[0]
        energy = j["energy"] if j else random.choices(ENERGIES[:3], ENERGY_WEIGHTS[:3])[0]

        log_lines = []
        for c in day_caps[:5]:
            t = c["created_at"].split(" ")[1][:5]
            d0 = json.loads(c["dimensions_json"])[0]
            log_lines.append(f"- [{t}] {c['message_text'][:80]}")

        content = f"""---
type: journal
date: "{date_str}"
mood: {mood or 'okay'}
energy: {energy or 'medium'}
icor_elements: {json.dumps(sorted(dims))}
---

# {day_name}

## Morning Intentions
- Focus on top priorities for the day

## Log
{chr(10).join(log_lines) if log_lines else '- Quiet day'}

## Reflections
A {"productive" if len(day_caps) > 3 else "balanced"} day touching {len(dims)} dimensions.

## Actions
{"".join(f"- [ ] {c['message_text'][:60]}{chr(10)}" for c in day_caps if c["is_actionable"])}"""

        fpath = daily_dir / f"{date_str}.md"
        fpath.write_text(content)
        files_created.append(str(fpath.relative_to(VAULT_PATH)))

    # 5 concepts
    concepts = [
        ("Spaced-Repetition-Learning", "seedling", "Mind & Growth",
         "Optimal review intervals for long-term retention.",
         ["Personal-Knowledge-Management", "Mind & Growth"]),
        ("RAG-Pipeline-Architecture", "growing", "Mind & Growth",
         "Retrieval-augmented generation combining vector search with structured queries.",
         ["Mind & Growth", "Systems & Environment"]),
        ("Personal-Knowledge-Management", "evergreen", "Mind & Growth",
         "Systems for capturing, organizing, and retrieving personal knowledge.",
         ["Spaced-Repetition-Learning", "Mind & Growth"]),
        ("Morning-Routine-Design", "seedling", "Health & Vitality",
         "Structured morning habits for energy and focus.",
         ["Health & Vitality", "Systems & Environment"]),
        ("Demo-Video-Production", "seedling", "Purpose & Impact",
         "Creating compelling product demo videos for stakeholders.",
         ["Purpose & Impact", "Mind & Growth"]),
    ]
    for name, status, dim, idea, links in concepts:
        content = f"""---
type: concept
status: {status}
icor_elements: ["{dim}"]
related_concepts: {json.dumps([l for l in links if l != dim])}
created: "{dates[3].strftime('%Y-%m-%d')}"
---

# {name.replace('-', ' ')}

## Core Idea
{idea}

## Connections
{chr(10).join(f'- [[{l}]]' for l in links)}

## Open Questions
- How does this connect to the broader system?
"""
        fpath = concepts_dir / f"{name}.md"
        fpath.write_text(content)
        files_created.append(str(fpath.relative_to(VAULT_PATH)))

    # 1 rolling memo in Demo/Reports
    memo = gen_rolling_memo(dates, captures, journals)
    memo_path = reports_dir / "rolling-memo.md"
    memo_path.write_text(memo)
    files_created.append(str(memo_path.relative_to(VAULT_PATH)))

    return files_created


def _gen_demo_journals(dates, captures):
    """Generate ~12 journal entries for demo mode (12 of 14 days, 2 skipped)."""
    n = len(dates)
    skip_indices = sorted(random.sample(range(n), min(2, n)))
    rows = []
    for di in range(n):
        if di in skip_indices:
            continue
        dt = dates[di]
        date_str = dt.strftime("%Y-%m-%d")
        day_captures = [c for c in captures if c["created_at"].startswith(date_str)]
        dims = set()
        for c in day_captures:
            dims.update(json.loads(c["dimensions_json"]))
        mood = random.choices(MOODS, MOOD_WEIGHTS)[0]
        energy = random.choices(ENERGIES, ENERGY_WEIGHTS)[0]
        content = f"# {dt.strftime('%A, %B %d, %Y')}\n\n## Morning\nStarted the day with focus.\n\n## Log\n"
        for c in day_captures[:3]:
            content += f"- {c['message_text'][:80]}\n"
        content += f"\n## Reflections\nProductive day overall. Touched {len(dims)} dimensions."
        summary = f"Day focused on {', '.join(list(dims)[:3]) or 'general activity'}."
        sentiment = round(random.uniform(0.4, 0.9), 2)
        rows.append({
            "date": date_str,
            "content": content,
            "mood": mood,
            "energy": energy,
            "icor_elements": json.dumps(list(dims)),
            "summary": summary,
            "sentiment_score": sentiment,
            "file_path": f"Daily Notes/{date_str}.md",
        })
    return rows


def run_demo_mode(args):
    """Execute demo mode: create isolated brain_demo.db + vault/Demo/ files."""
    db_path = PROJECT_ROOT / "data" / "brain_demo.db"
    anchor = datetime.fromisoformat(args.date_anchor) if args.date_anchor else datetime.now()
    dates = _demo_dates(anchor, 14)
    n_days = len(dates)

    # Generate all leaf data
    random.seed(args.seed)
    captures = gen_demo_captures(dates)
    classifications = gen_demo_classifications(captures)
    journals = _gen_demo_journals(dates, captures)
    action_items = gen_demo_action_items(dates, captures)
    reminders = gen_demo_reminders(action_items)
    kw_feedback = gen_demo_keyword_feedback()
    ext_feedback = gen_demo_extraction_feedback(captures)

    if args.dry_run:
        print("=== DEMO DRY RUN ===")
        print(f"DB target:            {db_path}")
        print(f"Date range:           {dates[0].date()} to {dates[-1].date()}")
        print(f"captures_log:         {len(captures)} rows")
        print(f"classifications:      {len(classifications)} rows")
        print(f"journal_entries:      {len(journals)} rows")
        print(f"action_items:         {len(action_items)} rows")
        print(f"reminders:            {len(reminders)} rows")
        print(f"keyword_feedback:     {len(kw_feedback)} rows")
        print(f"extraction_feedback:  {len(ext_feedback)} rows")
        print(f"vault files:          14 daily notes + 5 concepts + 1 memo")
        return

    # Delete existing demo DB (idempotent)
    for f in PROJECT_ROOT.joinpath("data").glob("brain_demo.db*"):
        f.unlink()

    # Create base schema via init-db.sh SQL piped to sqlite3
    init_script = PROJECT_ROOT / "scripts" / "init-db.sh"
    # Extract the SQL between <<'SQL' and SQL markers
    init_text = init_script.read_text()
    sql_start = init_text.index("<<'SQL'") + len("<<'SQL'")
    sql_end = init_text.index("\nSQL\n", sql_start)
    init_sql = init_text[sql_start:sql_end]
    conn_init = sqlite3.connect(str(db_path))
    conn_init.executescript(init_sql)
    conn_init.close()
    print(f"Created base tables in {db_path}")

    # Apply migrations on top
    migrate_script = PROJECT_ROOT / "scripts" / "migrate-db.py"
    result = subprocess.run(
        [sys.executable, str(migrate_script), str(db_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: migrate-db.py failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"Applied migrations via migrate-db.py")

    # Insert leaf data
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute("BEGIN")

    # captures_log
    for c in captures:
        conn.execute(
            "INSERT INTO captures_log (message_text, dimensions_json, confidence, method, is_actionable, source_channel, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (c["message_text"], c["dimensions_json"], c["confidence"], c["method"],
             c["is_actionable"], c["source_channel"], c["created_at"]),
        )
    print(f"  captures_log: {len(captures)} rows")

    # Get capture IDs for FK references
    cap_ids = [r[0] for r in conn.execute("SELECT id FROM captures_log ORDER BY id").fetchall()]

    # classifications
    for cl in classifications:
        conn.execute(
            "INSERT INTO classifications (message_text, message_ts, primary_dimension, confidence, method, all_scores_json, user_correction, corrected_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cl["message_text"], cl["message_ts"], cl["primary_dimension"], cl["confidence"],
             cl["method"], cl["all_scores_json"], cl["user_correction"], cl["corrected_at"], cl["created_at"]),
        )
    print(f"  classifications: {len(classifications)} rows")

    # journal_entries
    for j in journals:
        conn.execute(
            "INSERT OR IGNORE INTO journal_entries (date, content, mood, energy, icor_elements, summary, sentiment_score, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (j["date"], j["content"], j["mood"], j["energy"],
             j["icor_elements"], j["summary"], j["sentiment_score"],
             f"Demo/Daily Notes/{j['date']}.md"),
        )
    print(f"  journal_entries: {len(journals)} rows")

    # action_items
    action_ids = []
    for a in action_items:
        cur = conn.execute(
            "INSERT INTO action_items (description, source_file, source_date, status, icor_element, created_at, completed_at, due_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (a["description"], a["source_file"], a["source_date"], a["status"],
             a["icor_element"], a["created_at"], a["completed_at"], a["due_date"]),
        )
        action_ids.append(cur.lastrowid)
    print(f"  action_items: {len(action_items)} rows")

    # reminders (FK to action_items)
    for r in reminders:
        aid = action_ids[r["action_index"]] if r["action_index"] < len(action_ids) else action_ids[0]
        conn.execute(
            "INSERT INTO reminders (action_item_id, remind_at, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            (aid, r["remind_at"], r["status"], r["created_at"]),
        )
    print(f"  reminders: {len(reminders)} rows")

    # keyword_feedback
    for kw in kw_feedback:
        conn.execute(
            "INSERT OR IGNORE INTO keyword_feedback (dimension, keyword, source, success_count, fail_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (kw["dimension"], kw["keyword"], kw["source"], kw["success_count"], kw["fail_count"]),
        )
    print(f"  keyword_feedback: {len(kw_feedback)} rows")

    # extraction_feedback (FK to captures_log)
    for ef in ext_feedback:
        cid = cap_ids[ef["capture_index"]] if ef["capture_index"] < len(cap_ids) else cap_ids[0]
        conn.execute(
            "INSERT INTO extraction_feedback (capture_id, field_name, proposed_value, confirmed_value, was_correct) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, ef["field_name"], ef["proposed_value"], ef["confirmed_value"], ef["was_correct"]),
        )
    print(f"  extraction_feedback: {len(ext_feedback)} rows")

    conn.execute("COMMIT")
    conn.close()

    # Create vault files
    vault_files = gen_demo_vault_files(dates, captures, journals)
    print(f"  vault files: {len(vault_files)} created in vault/Demo/")

    print(f"\nDemo data ready at {db_path}")
    print(f"Next: source scripts/demo-env.sh && run derivation pipeline")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic eval data")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Create isolated brain_demo.db + vault/Demo/")
    parser.add_argument("--clean", action="store_true", help="Remove demo artifacts and exit")
    parser.add_argument("--date-anchor", type=str, default=None, help="ISO date for T-0 (default: today)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    args = parser.parse_args()

    # Clean mode: remove demo artifacts and exit
    if args.clean:
        for f in PROJECT_ROOT.joinpath("data").glob("brain_demo.db*"):
            f.unlink()
            print(f"  Removed {f}")
        demo_vault = PROJECT_ROOT / "vault" / "Demo"
        if demo_vault.exists():
            shutil.rmtree(demo_vault)
            print(f"  Removed {demo_vault}")
        print("Cleaned: brain_demo.db* + vault/Demo/")
        return

    # Demo mode: isolated DB + vault files
    if args.demo:
        run_demo_mode(args)
        return

    db_path = args.db_path
    dates = gen_dates()

    # Generate all data
    captures = gen_captures(dates)
    search_logs = gen_search_logs(dates)
    journals = gen_journal_entries(dates, captures)
    engagement = gen_engagement(dates, captures, journals)
    edges = gen_vault_edges()
    memo_content = gen_rolling_memo(dates, captures, journals)

    if args.dry_run:
        print(f"=== DRY RUN ===")
        print(f"captures_log:         {len(captures)} rows")
        print(f"search_log:           {len(search_logs)} rows")
        print(f"journal_entries:      {len(journals)} rows")
        print(f"engagement_daily:     {len(engagement)} rows")
        print(f"graduation_proposals: 4 rows")
        print(f"vault_edges:          {len(edges)} rows")
        print(f"rolling-memo.md:      {DAYS} daily entries")
        print(f"\nDate range: {DATE_START.date()} to {DATE_END.date()}")
        return

    # Backup
    backup = db_path.with_suffix(".db.pre-eval-sim")
    if not backup.exists():
        shutil.copy2(db_path, backup)
        print(f"Backed up to {backup}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Insert captures
    for c in captures:
        conn.execute(
            "INSERT INTO captures_log (message_text, dimensions_json, confidence, method, is_actionable, source_channel, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (c["message_text"], c["dimensions_json"], c["confidence"], c["method"],
             c["is_actionable"], c["source_channel"], c["created_at"]),
        )
    print(f"Inserted {len(captures)} captures_log rows")

    # Get inserted capture IDs grouped by dimension for graduation proposals
    cursor = conn.execute(
        "SELECT id, dimensions_json FROM captures_log WHERE created_at >= '2026-03-28' ORDER BY id"
    )
    capture_ids_by_dim = {}
    for row in cursor:
        dims = json.loads(row[1])
        for d in dims:
            capture_ids_by_dim.setdefault(d, []).append(row[0])

    # Insert graduation proposals
    proposals = gen_graduation_proposals(capture_ids_by_dim)
    for p in proposals:
        conn.execute(
            "INSERT OR IGNORE INTO graduation_proposals "
            "(cluster_hash, proposed_title, proposed_dimension, source_capture_ids, source_texts, "
            "status, message_id, proposed_at, resolved_at, snooze_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["cluster_hash"], p["proposed_title"], p["proposed_dimension"],
             p["source_capture_ids"], p["source_texts"], p["status"],
             p["message_id"], p["proposed_at"], p["resolved_at"], p["snooze_until"]),
        )
    print(f"Inserted {len(proposals)} graduation_proposals rows")

    # Insert search logs
    for s in search_logs:
        conn.execute(
            "INSERT INTO search_log (query, command, channel_rankings, rrf_ranking, "
            "channels_used, total_candidates, result_count, elapsed_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (s["query"], s["command"], s["channel_rankings"], s["rrf_ranking"],
             s["channels_used"], s["total_candidates"], s["result_count"],
             s["elapsed_ms"], s["created_at"]),
        )
    print(f"Inserted {len(search_logs)} search_log rows")

    # Insert journal entries
    for j in journals:
        conn.execute(
            "INSERT OR IGNORE INTO journal_entries (date, content, mood, energy, icor_elements, summary, sentiment_score, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (j["date"], j["content"], j["mood"], j["energy"],
             j["icor_elements"], j["summary"], j["sentiment_score"], j["file_path"]),
        )
    print(f"Inserted {len(journals)} journal_entries rows")

    # Insert engagement
    for e in engagement:
        conn.execute(
            "INSERT OR IGNORE INTO engagement_daily "
            "(date, captures_count, actionable_captures, actions_created, actions_completed, "
            "actions_pending, journal_entry_count, journal_word_count, avg_sentiment, mood, energy, "
            "dimension_mentions_json, vault_files_modified, vault_files_created, edges_created, "
            "notion_items_synced, engagement_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e["date"], e["captures_count"], e["actionable_captures"], e["actions_created"],
             e["actions_completed"], e["actions_pending"], e["journal_entry_count"],
             e["journal_word_count"], e["avg_sentiment"], e["mood"], e["energy"],
             e["dimension_mentions_json"], e["vault_files_modified"], e["vault_files_created"],
             e["edges_created"], e["notion_items_synced"], e["engagement_score"]),
        )
    print(f"Inserted {len(engagement)} engagement_daily rows")

    # Insert edges
    for edge in edges:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO vault_edges "
                "(source_node_id, target_node_id, edge_type, weight, metadata_json, verified_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (edge["source_node_id"], edge["target_node_id"], edge["edge_type"],
                 edge["weight"], edge["metadata_json"], edge["verified_at"]),
            )
        except sqlite3.IntegrityError:
            pass  # Edge already exists
    print(f"Inserted up to {len(edges)} vault_edges rows")

    conn.commit()
    conn.close()

    # Write rolling memo
    memo_path = VAULT_PATH / "Reports" / "rolling-memo.md"
    memo_path.parent.mkdir(parents=True, exist_ok=True)
    memo_path.write_text(memo_content)
    print(f"Wrote {memo_path} ({len(memo_content)} chars, {DAYS} entries)")

    print(f"\nDone. Run: python scripts/evaluate_kill_criteria.py")


if __name__ == "__main__":
    main()

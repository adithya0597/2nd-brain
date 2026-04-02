#!/usr/bin/env python3
"""Evaluate multi-label classification F1-score.

Tests whether the classifier returns ALL correct dimensions
for messages that span multiple life areas.

Metrics:
  - Per-sample F1 (macro): average F1 across all samples
  - Precision: of returned dimensions, how many are correct?
  - Recall: of expected dimensions, how many were returned?

Usage:
    python tests/eval_multilabel.py

Output (last line):
    MULTILABEL_F1: 45.2% | precision=60.0% recall=35.0%
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

for mod_name in [
    "telegram", "telegram.ext", "telegram.constants",
    "aiosqlite", "notion_client",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

import config
config.ANTHROPIC_API_KEY = None  # Disable LLM tier

from core.classifier import MessageClassifier

# Multi-label corpus: messages that genuinely span multiple dimensions
CORPUS = [
    {
        "text": "I woke up late as i was trying to build you my 2nd brain. Did a couple more fixes. I really should start prepping for my AI/ML engineer interview and focus on getting a job fast. Evening naps are soo bad for me. An hour later I forced myself to workout. Hitting legs today",
        "expected": ["Health & Vitality", "Wealth & Finance", "Systems & Environment"],
        "note": "Sleep/workout (Health), interview/job (Wealth), building 2nd brain (Systems)"
    },
    {
        "text": "1. New changes to my linkedin outreach program and 2nd brain making it all functional. 2. Time management was hard and i couldn't focus on applying for jobs and interview prep. 3. Start every day with pushups, squats and pull ups. Then apply for jobs. 2nd half workout and learn AI. 4. Notebooklm and AI to learn AI",
        "expected": ["Wealth & Finance", "Health & Vitality", "Mind & Growth"],
        "note": "Job apps (Wealth), exercise (Health), learning AI (Mind)"
    },
    {
        "text": "Had a great workout this morning, 5k run. Then spent 3 hours prepping for the Wells Fargo interview. Called mom to talk about job stress.",
        "expected": ["Health & Vitality", "Wealth & Finance", "Relationships"],
        "note": "Workout (Health), interview prep (Wealth), family call (Relationships)"
    },
    {
        "text": "Danielle Spiedel a chief of staff of wells fargo wants me to have a conversation with departing director of data engineering John parker. I also had the call with Scott W Evans on guidance for pitch deck and networking plan.",
        "expected": ["Wealth & Finance", "Relationships"],
        "note": "Professional networking for job (Wealth + Relationships)"
    },
    {
        "text": "These are times 2nd brain, alot is at stake. I started learning fabric and how my conversation with job could go. Norm Fleming also reached out. I need grind on fabric and other concepts tomorrow.",
        "expected": ["Wealth & Finance", "Mind & Growth"],
        "note": "Interview prep (Wealth), learning Fabric (Mind)"
    },
    {
        "text": "Set up automated backup scripts, reorganized Obsidian vault, then wrote a blog post about knowledge graph best practices for the community",
        "expected": ["Systems & Environment", "Purpose & Impact"],
        "note": "Automation/tooling (Systems), thought leadership (Purpose)"
    },
    {
        "text": "Meal prepped chicken and rice for the week, reviewed my budget spreadsheet, paid rent",
        "expected": ["Health & Vitality", "Wealth & Finance"],
        "note": "Nutrition (Health), budgeting (Wealth)"
    },
    {
        "text": "Deep conversation with my partner about our financial goals and savings plan for the house",
        "expected": ["Relationships", "Wealth & Finance"],
        "note": "Partner relationship (Relationships), financial planning (Wealth)"
    },
    {
        "text": "Finished reading Thinking Fast and Slow. Key insight about System 1 vs System 2 applies directly to how I mentor junior devs at work",
        "expected": ["Mind & Growth", "Purpose & Impact"],
        "note": "Reading/learning (Mind), mentoring (Purpose)"
    },
    {
        "text": "Built a new CI/CD pipeline for the team project, documented everything in the wiki for future contributors",
        "expected": ["Systems & Environment", "Purpose & Impact"],
        "note": "Infrastructure (Systems), community contribution (Purpose)"
    },
    {
        "text": "Send a post on linkedin how every major enterprise is looking for data engineers with knowledge graphs and ai",
        "expected": ["Wealth & Finance", "Purpose & Impact"],
        "note": "LinkedIn positioning (Wealth), thought leadership (Purpose)"
    },
    {
        "text": "I can use perplexity to scan jobs and do a job fit analysis through semantic and keyword analysis. This would resolve my job search problem.",
        "expected": ["Wealth & Finance", "Systems & Environment"],
        "note": "Job search (Wealth), building automation (Systems)"
    },
    {
        "text": "Volunteered at food bank, then went for a long run to clear my head",
        "expected": ["Purpose & Impact", "Health & Vitality"],
        "note": "Volunteering (Purpose), running (Health)"
    },
    {
        "text": "Applied to 12 jobs today. Spent the evening studying system design patterns for interviews",
        "expected": ["Wealth & Finance", "Mind & Growth"],
        "note": "Job applications (Wealth), studying (Mind)"
    }
]


def run_eval():
    classifier = MessageClassifier()

    sample_f1s = []
    total_precision_num = 0
    total_precision_den = 0
    total_recall_num = 0
    total_recall_den = 0
    errors = []

    for item in CORPUS:
        text = item["text"]
        expected = set(item["expected"])

        result = classifier.classify(text)
        predicted = set()
        if not result.is_noise and result.matches:
            predicted = {m.dimension for m in result.matches}

        # Per-sample precision/recall/F1
        tp = len(predicted & expected)
        p = tp / len(predicted) if predicted else 0
        r = tp / len(expected) if expected else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        sample_f1s.append(f1)

        total_precision_num += tp
        total_precision_den += len(predicted)
        total_recall_num += tp
        total_recall_den += len(expected)

        if f1 < 1.0:
            missing = expected - predicted
            spurious = predicted - expected
            details = []
            if missing:
                details.append(f"missing={sorted(missing)}")
            if spurious:
                details.append(f"spurious={sorted(spurious)}")
            methods = [(m.dimension, m.confidence, m.method) for m in (result.matches or [])]
            errors.append(
                f"  F1={f1:.2f}: expected={sorted(expected)} got={sorted(predicted)} "
                f"{' '.join(details)}\n"
                f"    scores: {methods}\n"
                f"    text: {text[:80]}..."
            )

    macro_f1 = sum(sample_f1s) / len(sample_f1s) * 100 if sample_f1s else 0
    micro_p = total_precision_num / total_precision_den * 100 if total_precision_den > 0 else 0
    micro_r = total_recall_num / total_recall_den * 100 if total_recall_den > 0 else 0

    if errors:
        print("Multi-label errors:")
        for e in errors:
            print(e)
        print()

    print(f"MULTILABEL_F1: {macro_f1:.1f}% | precision={micro_p:.1f}% recall={micro_r:.1f}%")
    return macro_f1


if __name__ == "__main__":
    run_eval()

#!/usr/bin/env python3
"""Evaluate classifier accuracy against labeled corpus.

Usage:
    python tests/eval_classifier_accuracy.py

Output (last line):
    ACCURACY: 65.7% (23/35)

Exit code 0 always (metric is printed, not asserted).
"""
import json
import os
import sys

# Ensure brain-bot is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must mock external deps before importing classifier
from unittest.mock import MagicMock

# Mock modules that aren't needed for classification eval
for mod_name in [
    "telegram", "telegram.ext", "telegram.constants",
    "aiosqlite", "notion_client",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Minimal config setup
import config
config.ANTHROPIC_API_KEY = None  # Disable LLM tier for eval (too expensive per iteration)

from core.classifier import MessageClassifier

CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_classification.json")


def run_eval():
    with open(CORPUS_PATH) as f:
        corpus = json.load(f)

    classifier = MessageClassifier()
    correct = 0
    total = 0
    errors = []

    for item in corpus:
        text = item["text"]
        expected = item["expected"]
        total += 1

        result = classifier.classify(text)

        # Noise check
        if expected == "NOISE":
            if result.is_noise:
                correct += 1
            else:
                got = result.matches[0].dimension if result.matches else "NO_MATCH"
                errors.append(f"  MISS: expected=NOISE got={got} | {text[:60]}")
            continue

        # Dimension check
        if result.is_noise:
            errors.append(f"  MISS: expected={expected} got=NOISE | {text[:60]}")
            continue

        if not result.matches:
            errors.append(f"  MISS: expected={expected} got=NO_MATCH | {text[:60]}")
            continue

        got = result.matches[0].dimension
        if got == expected:
            correct += 1
        else:
            conf = result.matches[0].confidence
            method = result.matches[0].method
            errors.append(
                f"  MISS: expected={expected} got={got} "
                f"(conf={conf:.2f}, method={method}) | {text[:60]}"
            )

    # Print details
    if errors:
        print("Misclassifications:")
        for e in errors:
            print(e)
        print()

    accuracy = correct / total * 100 if total > 0 else 0
    print(f"ACCURACY: {accuracy:.1f}% ({correct}/{total})")
    return accuracy


if __name__ == "__main__":
    run_eval()

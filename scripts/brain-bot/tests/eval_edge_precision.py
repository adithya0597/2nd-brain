#!/usr/bin/env python3
"""Evaluate ICOR affinity edge precision against labeled ground truth.

Measures whether the icor_affinity edges in vault_edges connect
each inbox file to the CORRECT ICOR dimensions.

Metrics:
  - Precision: % of created edges that are correct
  - Recall: % of expected edges that were created
  - F1: harmonic mean
  - Edge accuracy: % of files where top-1 edge matches any expected dimension

Usage:
    python tests/eval_edge_precision.py

Output (last line):
    EDGE_F1: 45.2% | precision=60.0% recall=35.0% | top1_acc=53.3%
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_edge_precision.json")


def run_eval():
    with open(CORPUS_PATH) as f:
        corpus = json.load(f)

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    total_expected = 0
    total_created_correct = 0
    total_created = 0
    top1_correct = 0
    top1_total = 0
    errors = []

    for item in corpus:
        file_path = item["file_path"]
        expected_dims = set(item["expected_dimensions"])

        # Get actual ICOR affinity edges for this file
        rows = conn.execute("""
            SELECT icor.title as dimension, ve.weight
            FROM vault_edges ve
            JOIN vault_nodes vn ON ve.source_node_id = vn.id
            JOIN vault_nodes icor ON ve.target_node_id = icor.id
            WHERE ve.edge_type = 'icor_affinity'
            AND vn.file_path = ?
            ORDER BY ve.weight DESC
        """, (file_path,)).fetchall()

        actual_dims = {row["dimension"] for row in rows}

        # Precision: of edges created, how many are correct?
        correct = actual_dims & expected_dims
        total_created += len(actual_dims)
        total_created_correct += len(correct)

        # Recall: of expected edges, how many were created?
        total_expected += len(expected_dims)

        # Top-1 accuracy
        top1_total += 1
        if rows:
            top1_dim = rows[0]["dimension"]
            if top1_dim in expected_dims:
                top1_correct += 1
            else:
                errors.append(
                    f"  TOP1 MISS: {file_path}\n"
                    f"    expected: {sorted(expected_dims)}\n"
                    f"    got top1: {top1_dim} ({rows[0]['weight']:.3f})\n"
                    f"    all edges: {[(r['dimension'], round(r['weight'], 3)) for r in rows]}"
                )
        else:
            errors.append(
                f"  NO EDGES: {file_path}\n"
                f"    expected: {sorted(expected_dims)}"
            )

        # Missing edges
        missing = expected_dims - actual_dims
        if missing:
            errors.append(
                f"  MISSING: {file_path}\n"
                f"    missing dims: {sorted(missing)}\n"
                f"    has edges: {[(r['dimension'], round(r['weight'], 3)) for r in rows]}"
            )

        # Spurious edges
        spurious = actual_dims - expected_dims
        if spurious:
            errors.append(
                f"  SPURIOUS: {file_path}\n"
                f"    wrong dims: {sorted(spurious)}\n"
                f"    expected: {sorted(expected_dims)}"
            )

    conn.close()

    precision = total_created_correct / total_created * 100 if total_created > 0 else 0
    recall = total_created_correct / total_expected * 100 if total_expected > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    top1_acc = top1_correct / top1_total * 100 if top1_total > 0 else 0

    if errors:
        print("Edge errors:")
        for e in errors:
            print(e)
        print()

    print(f"EDGE_F1: {f1:.1f}% | precision={precision:.1f}% recall={recall:.1f}% | top1_acc={top1_acc:.1f}%")
    return f1


if __name__ == "__main__":
    run_eval()

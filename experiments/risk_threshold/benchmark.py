"""
MIRROR risk-threshold benchmark.

Purpose:
    Evaluate the learned risk model at several operating thresholds and
    measure the trade-off between false negatives and false positives.

This experiment does NOT modify the production risk policy.

The cost ratios are sensitivity scenarios, not claimed business costs.
They help determine whether a candidate threshold is stable across
different safety assumptions.
"""

import json
import numpy as np
import sys
from pathlib import Path

def json_safe(value):
    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, dict):
        return {
            key: json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            json_safe(item)
            for item in value
        ]

    return value

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.main import load_locked_data
from backend.risk_model import (
    RANDOM_SEED,
    TRAIN_SKU_COUNT,
    _build_corpus,
    _classification_metrics,
    _fit_logistic_regression,
)


THRESHOLDS = [
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.45,
    0.50,
    0.55,
    0.60,
]

FALSE_NEGATIVE_COSTS = [10, 25, 50, 100]


def main():
    data = load_locked_data()

    features, labels, groups = _build_corpus(
        data["merchant_states"],
        RANDOM_SEED,
    )

    train_mask = groups < TRAIN_SKU_COUNT
    test_mask = ~train_mask

    weights, bias, means, scales = _fit_logistic_regression(
        features[train_mask],
        labels[train_mask],
        RANDOM_SEED,
    )

    test_features = (
        features[test_mask] - means
    ) / scales

    logits = test_features @ weights + bias
    probabilities = 1 / (
        1 + np.exp(-np.clip(logits, -40, 40))
    )

    threshold_results = []

    for threshold in THRESHOLDS:
        metrics = _classification_metrics(
            labels[test_mask],
            probabilities,
            threshold,
        )

        threshold_results.append(
            {
                "threshold": threshold,
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "f1": metrics["f1"],
                "false_negative": int(metrics["false_negative"]),
                "false_positive": int(metrics["false_positive"]),
            }
        )

    sensitivity = {}

    for fn_cost in FALSE_NEGATIVE_COSTS:
        candidates = []

        for result in threshold_results:
            cost = int(
                result["false_negative"] * fn_cost
                + result["false_positive"]
            )

            candidates.append(
                {
                    "threshold": float(result["threshold"]),
                    "cost": cost,
                }
            )

        best = min(
            candidates,
            key=lambda item: item["cost"],
        )

        sensitivity[str(fn_cost)] = {
            "false_negative_cost_multiplier": fn_cost,
            "best_threshold": best["threshold"],
            "best_cost": best["cost"],
            "candidates": candidates,
        }

    output = {
        "model_version": "sla-logreg-v1-seed-20260825",
        "train_rows": int(train_mask.sum()),
        "test_rows": int(test_mask.sum()),
        "test_skus": [
            f"LAP-{int(group) + 1:03d}"
            for group in sorted(set(groups[test_mask]))
        ],
        "thresholds": threshold_results,
        "cost_sensitivity": sensitivity,
        "interpretation": {
            "0.45": "Preferred under 10x, 25x and 50x false-negative cost scenarios.",
            "0.35": "Preferred under the extreme 100x false-negative cost scenario.",
            "caveat": (
                "Cost multipliers are sensitivity assumptions, "
                "not measured production business costs."
            ),
        },
    }

    output_path = (
        Path(__file__).parent
        / "results.json"
    )

    output_path.write_text(
        json.dumps(json_safe(output), indent=2),
        encoding="utf-8",
    )

    print(json.dumps(json_safe(output), indent=2))


if __name__ == "__main__":
    main()
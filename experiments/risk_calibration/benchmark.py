"""
MIRROR three-way risk calibration benchmark.

The experiment uses SKU-group separation:

    LAP-001..035 -> model training
    LAP-036..040 -> calibration fitting
    LAP-041..050 -> untouched final evaluation

The final evaluation set is never used to fit either the predictive
model or the calibration transform.

This experiment does NOT modify production risk_model.py.
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.main import load_locked_data
from backend.risk_model import (
    RANDOM_SEED,
    _build_corpus,
    _fit_logistic_regression,
    _sigmoid,
)


TRAIN_SKUS = 35
CALIBRATION_SKUS = 5

BIN_EDGES = np.linspace(0.0, 1.0, 11)


def brier_score(y_true, probabilities):
    return float(
        np.mean(
            (probabilities - y_true) ** 2
        )
    )


def calibration_bins(y_true, probabilities):
    rows = []

    for lower, upper in zip(
        BIN_EDGES[:-1],
        BIN_EDGES[1:],
    ):
        if upper == 1.0:
            mask = (
                (probabilities >= lower)
                & (probabilities <= upper)
            )
        else:
            mask = (
                (probabilities >= lower)
                & (probabilities < upper)
            )

        count = int(mask.sum())

        if count == 0:
            continue

        predicted_mean = float(
            probabilities[mask].mean()
        )

        observed_rate = float(
            y_true[mask].mean()
        )

        rows.append(
            {
                "lower": float(lower),
                "upper": float(upper),
                "count": count,
                "predicted_mean": predicted_mean,
                "observed_rate": observed_rate,
                "absolute_gap": abs(
                    predicted_mean - observed_rate
                ),
            }
        )

    return rows


def expected_calibration_error(bins):
    total = sum(
        row["count"]
        for row in bins
    )

    if total == 0:
        return 0.0

    return float(
        sum(
            row["count"]
            * row["absolute_gap"]
            for row in bins
        )
        / total
    )


def fit_platt_scaling(
    probabilities,
    labels,
):
    """
    Fit a one-dimensional logistic calibration transform.

    The original model probabilities are converted to logits:

        z = log(p / (1-p))

    Then a second logistic model learns:

        calibrated_p = sigmoid(a * z + b)

    Calibration parameters are learned ONLY from the calibration SKU groups.
    """

    eps = 1e-6

    probabilities = np.clip(
        probabilities,
        eps,
        1.0 - eps,
    )

    logits = np.log(
        probabilities
        / (1.0 - probabilities)
    )

    x = np.column_stack(
        [
            np.ones(len(logits)),
            logits,
        ]
    )

    weights = np.zeros(2)

    for _ in range(200):
        fitted = _sigmoid(
            x @ weights
        )

        gradient = (
            x.T
            @ (fitted - labels)
        )

        weights_diag = (
            fitted
            * (1.0 - fitted)
        )

        hessian = (
            x.T
            @ (x * weights_diag[:, None])
        )

        hessian += (
            np.eye(2)
            * 1e-8
        )

        step = np.linalg.solve(
            hessian,
            gradient,
        )

        weights -= step

        if np.max(
            np.abs(step)
        ) < 1e-8:
            break

    return float(weights[0]), float(weights[1])


def apply_platt_scaling(
    probabilities,
    intercept,
    slope,
):
    eps = 1e-6

    probabilities = np.clip(
        probabilities,
        eps,
        1.0 - eps,
    )

    logits = np.log(
        probabilities
        / (1.0 - probabilities)
    )

    return _sigmoid(
        intercept
        + slope * logits
    )


def evaluate(
    labels,
    probabilities,
):
    bins = calibration_bins(
        labels,
        probabilities,
    )

    return {
        "brier_score": brier_score(
            labels,
            probabilities,
        ),
        "expected_calibration_error": (
            expected_calibration_error(
                bins
            )
        ),
        "bins": bins,
    }

def binary_classification_metrics(
    y_true,
    probabilities,
    threshold,
):
    predicted = probabilities >= threshold

    true_positive = int(
        np.sum(predicted & (y_true == 1))
    )
    false_positive = int(
        np.sum(predicted & (y_true == 0))
    )
    false_negative = int(
        np.sum(~predicted & (y_true == 1))
    )
    true_negative = int(
        np.sum(~predicted & (y_true == 0))
    )

    precision = (
        true_positive
        / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )

    recall = (
        true_positive
        / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )

    f1 = (
        2.0 * precision * recall
        / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
    }


def roc_auc_score(y_true, probabilities):
    """
    Compute ROC-AUC from ranking directly.

    No external ML dependency is required.
    """

    y_true = np.asarray(y_true)
    probabilities = np.asarray(probabilities)

    positives = y_true == 1
    negatives = y_true == 0

    positive_count = int(positives.sum())
    negative_count = int(negatives.sum())

    if positive_count == 0 or negative_count == 0:
        return 0.0

    order = np.argsort(
        probabilities,
        kind="mergesort",
    )

    sorted_scores = probabilities[order]

    ranks = np.empty(
        len(sorted_scores),
        dtype=float,
    )

    start = 0

    while start < len(sorted_scores):
        end = start + 1

        while (
            end < len(sorted_scores)
            and sorted_scores[end]
            == sorted_scores[start]
        ):
            end += 1

        average_rank = (
            start + 1 + end
        ) / 2.0

        ranks[start:end] = average_rank

        start = end

    original_ranks = np.empty_like(ranks)
    original_ranks[order] = ranks

    positive_rank_sum = float(
        original_ranks[positives].sum()
    )

    return float(
        (
            positive_rank_sum
            - positive_count
            * (positive_count + 1)
            / 2.0
        )
        / (
            positive_count
            * negative_count
        )
    )


def main():
    data = load_locked_data()

    features, labels, groups = _build_corpus(
        data["merchant_states"],
        RANDOM_SEED,
    )

    train_mask = groups < TRAIN_SKUS

    calibration_mask = (
        (groups >= TRAIN_SKUS)
        & (
            groups
            < TRAIN_SKUS + CALIBRATION_SKUS
        )
    )

    test_mask = (
        groups
        >= TRAIN_SKUS + CALIBRATION_SKUS
    )

    weights, bias, means, scales = (
        _fit_logistic_regression(
            features[train_mask],
            labels[train_mask],
            RANDOM_SEED,
        )
    )

    def predict(mask):
        normalized = (
            features[mask] - means
        ) / scales

        return _sigmoid(
            normalized @ weights + bias
        )

    calibration_probabilities = predict(
        calibration_mask
    )

    test_probabilities = predict(
        test_mask
    )

    calibration_intercept, calibration_slope = (
        fit_platt_scaling(
            calibration_probabilities,
            labels[calibration_mask],
        )
    )

    calibrated_test_probabilities = (
        apply_platt_scaling(
            test_probabilities,
            calibration_intercept,
            calibration_slope,
        )
    )

    y_test = labels[test_mask]

    raw_metrics = evaluate(
        y_test,
        test_probabilities,
    )

    calibrated_metrics = evaluate(
        y_test,
        calibrated_test_probabilities,
    )

    thresholds = [
        0.001,
        0.005,
        0.010,
        0.015,
        0.020,
        0.025,
        0.030,
        0.035,
        0.040,
        0.045,
        0.050,
        0.060,
        0.070,
        0.080,
        0.090,
        0.100,
        0.125,
        0.150,
        0.175,
        0.200,
        0.250,
        0.300,
        0.350,
        0.400,
        0.450,
        0.500,
        0.550,
        0.600,
        0.650,
        0.700,
        0.750,
        0.800,
        0.850,
        0.900,
        0.950,
    ]

    threshold_comparison = []

    for threshold in thresholds:
        raw = binary_classification_metrics(
            y_test,
            test_probabilities,
            threshold,
        )

        calibrated = binary_classification_metrics(
            y_test,
            calibrated_test_probabilities,
            threshold,
        )

        threshold_comparison.append(
            {
                "threshold": threshold,
                "raw": raw,
                "calibrated": calibrated,
            }
        )

    cost_multipliers = [
        10,
        25,
        50,
        100,
    ]

    calibrated_cost_sensitivity = {}

    for multiplier in cost_multipliers:
        candidates = []

        for threshold in thresholds:
            metrics = binary_classification_metrics(
                y_test,
                calibrated_test_probabilities,
                threshold,
            )

            cost = (
                metrics["false_positive"]
                + multiplier
                * metrics["false_negative"]
            )

            candidates.append(
                {
                    "threshold": threshold,
                    "cost": int(cost),
                    "false_positive": (
                        metrics["false_positive"]
                    ),
                    "false_negative": (
                        metrics["false_negative"]
                    ),
                }
            )

        best = min(
            candidates,
            key=lambda row: (
                row["cost"],
                row["threshold"],
            ),
        )

        calibrated_cost_sensitivity[
            str(multiplier)
        ] = {
            "false_negative_cost_multiplier": multiplier,
            "best_threshold": best["threshold"],
            "best_cost": best["cost"],
            "candidates": candidates,
        }

    raw_auc = roc_auc_score(
        y_test,
        test_probabilities,
    )

    calibrated_auc = roc_auc_score(
        y_test,
        calibrated_test_probabilities,
    )

    discrimination = {
        "raw_roc_auc": raw_auc,
        "calibrated_roc_auc": calibrated_auc,
        "absolute_auc_difference": abs(
            raw_auc - calibrated_auc
        ),
    }

    output = {
        "model_version": (
            f"sla-logreg-v1-seed-{RANDOM_SEED}"
        ),
        "split": {
            "training_skus": [
                f"LAP-{index + 1:03d}"
                for index in range(
                    TRAIN_SKUS
                )
            ],
            "calibration_skus": [
                f"LAP-{index + 1:03d}"
                for index in range(
                    TRAIN_SKUS,
                    TRAIN_SKUS + CALIBRATION_SKUS,
                )
            ],
            "test_skus": [
                f"LAP-{index + 1:03d}"
                for index in range(
                    TRAIN_SKUS + CALIBRATION_SKUS,
                    len(data["merchant_states"]),
                )
            ],
        },
        "rows": {
            "training": int(
                train_mask.sum()
            ),
            "calibration": int(
                calibration_mask.sum()
            ),
            "test": int(
                test_mask.sum()
            ),
        },
        "calibration_parameters": {
            "intercept": calibration_intercept,
            "slope": calibration_slope,
        },
        "raw_test_metrics": raw_metrics,
        "calibrated_test_metrics": calibrated_metrics,
        "discrimination": discrimination,
        "threshold_comparison": threshold_comparison,
        "calibrated_cost_sensitivity": (
            calibrated_cost_sensitivity
        ),
        "interpretation": {
            "rule": (
                "Calibration parameters are fitted only "
                "on calibration SKUs. Final metrics are "
                "computed only on untouched test SKUs."
            ),
            "warning": (
                "The experiment uses locked synthetic data "
                "and does not establish calibration on "
                "real production merchant traffic."
            ),
        },
    }

    output_path = (
        Path(__file__).parent
        / "three_way_results.json"
    )

    output_path.write_text(
        json.dumps(
            output,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            output,
            indent=2,
        )
    )
if __name__ == "__main__":
    main()
"""MIRROR's first learned risk component.

The existing decision engine is simulation-driven. This module adds a separate
predictive layer rather than replacing that engine. The model learns to estimate
SLA-miss probability from the same locked merchant state used by MIRROR.

Important boundary:
    The training labels are generated from MIRROR's synthetic demand simulator.
    This is a real ML model and a reproducible benchmark, but it is NOT presented
    as production performance on real merchant traffic. A later milestone will
    replace/augment the synthetic corpus with held-out real or competition data.

Why logistic regression here?
    For the first model we want a small, inspectable baseline. Its coefficients,
    feature scaling and decision threshold are easy to audit. A more expressive
    model is only useful after this baseline has an honest held-out benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import ceil
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np


FEATURE_NAMES: Tuple[str, ...] = (
    "requested_quantity",
    "delivery_window_days",
    "net_inventory",
    "incoming_quantity",
    "incoming_due",
    "demand_mean",
    "demand_shape",
    "quantity_to_inventory",
    "quantity_to_expected_demand",
    "inventory_cover_days",
)

# We deliberately use a conservative threshold for the first safety model.
# A false negative means we missed a risky fulfilment, which is more expensive
# to the recovery system than asking for a second look at a safe request.
DEFAULT_THRESHOLD = 0.35
TRAIN_SKU_COUNT = 40
SAMPLES_PER_SCENARIO = 50
QUANTITY_PRESSURES = (0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 3.00)
WINDOWS = (2, 3, 5, 7, 10)
RANDOM_SEED = 20260825


@dataclass(frozen=True)
class RiskModel:
    """Frozen model parameters and evaluation metadata.

    Keeping the learned parameters immutable makes the prediction path easy to
    reason about and prevents an API request from silently changing the model.
    """

    feature_names: Tuple[str, ...]
    means: Tuple[float, ...]
    scales: Tuple[float, ...]
    weights: Tuple[float, ...]
    bias: float
    threshold: float
    version: str
    metrics: Dict[str, float]
    train_rows: int
    test_rows: int
    test_skus: Tuple[str, ...]

    def predict_probability(self, features: Sequence[float]) -> float:
        if len(features) != len(self.feature_names):
            raise ValueError(f"Expected {len(self.feature_names)} features, got {len(features)}")
        x = (np.asarray(features, dtype=float) - np.asarray(self.means)) / np.asarray(self.scales)
        score = float(np.dot(x, np.asarray(self.weights)) + self.bias)
        # Clipping avoids overflow in exp() for deliberately extreme inputs.
        score = float(np.clip(score, -40.0, 40.0))
        return 1.0 / (1.0 + np.exp(-score))

    def explain(self, features: Sequence[float], top_k: int = 4) -> List[Dict[str, float]]:
        """Return signed feature contributions for a human-readable audit view."""
        if len(features) != len(self.feature_names):
            raise ValueError(f"Expected {len(self.feature_names)} features, got {len(features)}")
        x = (np.asarray(features, dtype=float) - np.asarray(self.means)) / np.asarray(self.scales)
        contributions = x * np.asarray(self.weights)
        order = np.argsort(np.abs(contributions))[::-1][:top_k]
        return [
            {
                "feature": self.feature_names[int(index)],
                "contribution": round(float(contributions[index]), 6),
                "value": round(float(features[index]), 6),
            }
            for index in order
        ]


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def _feature_row(state: Dict, quantity: int, days: int) -> List[float]:
    net_inventory = max(0.0, float(state["on_hand"] - state["reserved"]))
    incoming_due = bool(state["incoming_exists"] and state["incoming_eta_days"] <= days)
    incoming_quantity = float(state["incoming_quantity"] if incoming_due else 0)
    available = net_inventory + incoming_quantity
    expected_demand = max(float(state["mu"]) * days, 1.0)
    return [
        float(quantity),
        float(days),
        net_inventory,
        incoming_quantity,
        float(incoming_due),
        float(state["mu"]),
        float(state["nb_k"]),
        float(quantity) / max(available, 1.0),
        float(quantity) / expected_demand,
        available / max(float(state["mu"]), 1e-6),
    ]


def _build_corpus(merchant_states: Sequence[Dict], seed: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create path-level labels from the locked stochastic demand process.

    Each row is one possible fulfilment situation. The label is whether demand
    consumes enough available stock to make the requested quantity impossible.
    SKU ids are returned separately so the evaluation can be split by SKU rather
    than randomly leaking nearly-identical rows into train and test.
    """
    rng = np.random.default_rng(seed)
    rows: List[List[float]] = []
    labels: List[int] = []
    groups: List[int] = []

    for sku_index, state in enumerate(merchant_states):
        for days in WINDOWS:
            for pressure in QUANTITY_PRESSURES:
                quantity = max(1, int(ceil(float(state["mu"]) * days * pressure)))
                p = float(state["nb_k"]) / (float(state["nb_k"]) + float(state["mu"]))
                demand = rng.negative_binomial(
                    n=int(state["nb_k"]),
                    p=p,
                    size=SAMPLES_PER_SCENARIO,
                )
                net_inventory = max(0.0, float(state["on_hand"] - state["reserved"]))
                incoming_due = bool(state["incoming_exists"] and state["incoming_eta_days"] <= days)
                incoming = float(state["incoming_quantity"] if incoming_due else 0)
                available = net_inventory + incoming - demand
                scenario_labels = (available < quantity).astype(np.int8)
                row = _feature_row(state, quantity, days)
                rows.extend([row] * SAMPLES_PER_SCENARIO)
                labels.extend(int(value) for value in scenario_labels)
                groups.extend([sku_index] * SAMPLES_PER_SCENARIO)

    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=np.int8), np.asarray(groups, dtype=int)


def _fit_logistic_regression(x: np.ndarray, y: np.ndarray, seed: int) -> Tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Fit a regularized logistic model using only NumPy.

    We keep the optimizer here instead of adding a heavy ML dependency. L2
    regularization stabilizes correlated inventory features and makes the first
    baseline deterministic across machines.
    """
    rng = np.random.default_rng(seed)
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    x_scaled = (x - means) / scales

    weights = rng.normal(0.0, 0.01, size=x.shape[1])
    bias = 0.0
    learning_rate = 0.08
    regularization = 0.01

    # Class weighting keeps the model from learning the trivial majority class.
    positive = max(int(y.sum()), 1)
    negative = max(len(y) - positive, 1)
    positive_weight = len(y) / (2.0 * positive)
    negative_weight = len(y) / (2.0 * negative)
    sample_weights = np.where(y == 1, positive_weight, negative_weight)

    for _ in range(350):
        probabilities = _sigmoid(x_scaled @ weights + bias)
        error = (probabilities - y) * sample_weights
        grad_w = (x_scaled.T @ error) / len(y) + regularization * weights
        grad_b = float(error.mean())
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b

    return weights, float(bias), means, scales


def _classification_metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> Dict[str, float]:
    predicted = probabilities >= threshold
    positive = y_true == 1
    negative = ~positive
    tp = int(np.sum(predicted & positive))
    fp = int(np.sum(predicted & negative))
    fn = int(np.sum(~predicted & positive))
    tn = int(np.sum(~predicted & negative))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    accuracy = (tp + tn) / max(len(y_true), 1)
    return {
        "threshold": threshold,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positive": float(tp),
        "false_positive": float(fp),
        "false_negative": float(fn),
        "true_negative": float(tn),
    }


def _auc_roc(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    """Compute ROC-AUC without a third-party metric dependency."""
    positives = int(np.sum(y_true == 1))
    negatives = int(np.sum(y_true == 0))
    if positives == 0 or negatives == 0:
        return 0.0
    order = np.argsort(probabilities, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(probabilities) + 1, dtype=float)
    positive_rank_sum = float(ranks[y_true == 1].sum())
    return (positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def train_risk_model(locked_data: Dict, seed: int = RANDOM_SEED) -> RiskModel:
    """Train and evaluate the baseline on SKU-held-out synthetic paths."""
    states = locked_data["merchant_states"]
    x, y, groups = _build_corpus(states, seed)

    train_mask = groups < TRAIN_SKU_COUNT
    test_mask = ~train_mask
    if not np.any(train_mask) or not np.any(test_mask):
        raise RuntimeError("Risk-model split produced an empty train or test set")

    weights, bias, means, scales = _fit_logistic_regression(x[train_mask], y[train_mask], seed)
    test_scaled = (x[test_mask] - means) / scales
    probabilities = _sigmoid(test_scaled @ weights + bias)
    metrics = _classification_metrics(y[test_mask], probabilities, DEFAULT_THRESHOLD)
    metrics["roc_auc"] = _auc_roc(y[test_mask], probabilities)
    metrics["positive_rate"] = float(y[test_mask].mean())

    test_skus = tuple(states[index]["sku_id"] for index in range(TRAIN_SKU_COUNT, len(states)))
    # The version is tied to the feature contract and training seed, not a timestamp.
    version = f"sla-logreg-v1-seed-{seed}"
    return RiskModel(
        feature_names=FEATURE_NAMES,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
        threshold=DEFAULT_THRESHOLD,
        version=version,
        metrics={key: float(value) for key, value in metrics.items()},
        train_rows=int(np.sum(train_mask)),
        test_rows=int(np.sum(test_mask)),
        test_skus=test_skus,
    )


def risk_features_for_request(state: Dict, requested_quantity: int, delivery_window_days: int) -> List[float]:
    if requested_quantity <= 0:
        raise ValueError("requested_quantity must be positive")
    if delivery_window_days < 0:
        raise ValueError("delivery_window_days must be non-negative")
    return _feature_row(state, requested_quantity, delivery_window_days)


@lru_cache(maxsize=1)
def get_risk_model() -> RiskModel:
    """Train once per process; subsequent predictions are just matrix arithmetic."""
    from backend.main import load_locked_data

    return train_risk_model(load_locked_data())

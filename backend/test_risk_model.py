import unittest

from backend.main import load_locked_data
from backend.risk_model import (
    DEFAULT_THRESHOLD,
    FEATURE_NAMES,
    get_risk_model,
    risk_features_for_request,
    train_risk_model,
)


class RiskModelTests(unittest.TestCase):
    def test_training_is_deterministic(self):
        data = load_locked_data()
        first = train_risk_model(data)
        second = train_risk_model(data)

        self.assertEqual(first.version, second.version)
        self.assertEqual(first.weights, second.weights)
        self.assertEqual(first.bias, second.bias)
        self.assertEqual(first.metrics, second.metrics)

    def test_held_out_evaluation_is_non_empty(self):
        model = get_risk_model()

        self.assertGreater(model.train_rows, 0)
        self.assertGreater(model.test_rows, 0)
        self.assertGreater(len(model.test_skus), 0)
        self.assertGreaterEqual(model.metrics["precision"], 0.0)
        self.assertLessEqual(model.metrics["precision"], 1.0)
        self.assertGreaterEqual(model.metrics["recall"], 0.0)
        self.assertLessEqual(model.metrics["recall"], 1.0)
        self.assertGreaterEqual(model.metrics["roc_auc"], 0.0)
        self.assertLessEqual(model.metrics["roc_auc"], 1.0)

    def test_prediction_is_bounded_and_explainable(self):
        data = load_locked_data()
        state = data["merchant_states"][0]
        features = risk_features_for_request(state, requested_quantity=10, delivery_window_days=5)
        model = get_risk_model()
        probability = model.predict_probability(features)

        self.assertEqual(len(features), len(FEATURE_NAMES))
        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)
        self.assertGreater(len(model.explain(features)), 0)
        self.assertGreater(DEFAULT_THRESHOLD, 0.0)
        self.assertLess(DEFAULT_THRESHOLD, 1.0)

    def test_invalid_request_features_are_rejected(self):
        state = load_locked_data()["merchant_states"][0]
        with self.assertRaises(ValueError):
            risk_features_for_request(state, requested_quantity=0, delivery_window_days=5)
        with self.assertRaises(ValueError):
            risk_features_for_request(state, requested_quantity=10, delivery_window_days=-1)


if __name__ == "__main__":
    unittest.main()

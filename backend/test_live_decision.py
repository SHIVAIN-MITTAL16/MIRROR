import unittest

from fastapi.testclient import TestClient

from backend.ai_app import app
from backend.main import load_locked_data


class LiveDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.sku = load_locked_data()["catalog_skus"][0]

    def test_live_decision_uses_ml_as_second_gate(self):
        response = self.client.post(
            "/ai/live-decision",
            json={
                "sku_id": self.sku["sku_id"],
                "requested_quantity": 10,
                "budget": self.sku["current_price"] * 10,
                "deadline_days": 5,
                "price_flexibility": "Medium",
                "quantity_flexibility": "Medium",
                "timing_flexibility": "Medium",
                "substitution_tolerance": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["decision"], {"ACCEPT", "NEGOTIATE", "REJECT"})
        self.assertIn("ml", body)
        self.assertTrue(body["ml"]["applied"])
        self.assertEqual(body["ml"]["ml_evaluated_count"], body["ml"]["p05_survivor_count"])
        self.assertEqual(body["ml_gate_rejections"], body["ml"]["ml_rejections"])
        self.assertGreaterEqual(body["candidate_count"], body["p05_gate_rejections"])
        self.assertTrue(body["evidence_status"].startswith("FRESH_DETERMINISTIC_EVALUATION_WITH_LIVE_ML"))

    def test_live_budget_is_a_real_baseline_constraint(self):
        quantity = 25
        budget = self.sku["current_price"] * quantity * 0.50
        response = self.client.post(
            "/ai/live-decision",
            json={
                "sku_id": self.sku["sku_id"],
                "requested_quantity": quantity,
                "budget": budget,
                "deadline_days": 5,
                "price_flexibility": "Medium",
                "quantity_flexibility": "Medium",
                "timing_flexibility": "Medium",
                "substitution_tolerance": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["buyer_request"]["baseline_feasible"])
        self.assertGreater(body["buyer_request"]["baseline_transaction_total"], body["buyer_request"]["buyer_budget_ceiling"])
        self.assertNotEqual(body["decision"], "ACCEPT")

    def test_high_budget_does_not_force_a_substitution(self):
        response = self.client.post(
            "/ai/live-decision",
            json={
                "sku_id": self.sku["sku_id"],
                "requested_quantity": 19,
                "budget": 150000000,
                "deadline_days": 7,
                "price_flexibility": "Medium",
                "quantity_flexibility": "Medium",
                "timing_flexibility": "Medium",
                "substitution_tolerance": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        if body["decision"] == "NEGOTIATE":
            self.assertNotEqual(body["selected"]["action_type"], "SUBSTITUTION")
        self.assertTrue(body["buyer_request"]["baseline_feasible"])

    def test_live_rejects_misleading_fallback_suggestions(self):
        response = self.client.post(
            "/ai/live-decision",
            json={
                "sku_id": self.sku["sku_id"],
                "requested_quantity": 25,
                "budget": self.sku["current_price"] * 25,
                "deadline_days": 5,
                "price_flexibility": "Medium",
                "quantity_flexibility": "Medium",
                "timing_flexibility": "Medium",
                "substitution_tolerance": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        if body["decision"] == "ACCEPT":
            self.assertEqual(body["top_safe_alternatives"], [])

    def test_live_decision_rejects_unknown_sku(self):
        response = self.client.post(
            "/ai/live-decision",
            json={
                "sku_id": "NOT-A-SKU",
                "requested_quantity": 10,
                "budget": 100000,
                "deadline_days": 5,
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_live_decision_validates_flexibility(self):
        response = self.client.post(
            "/ai/live-decision",
            json={
                "sku_id": self.sku["sku_id"],
                "requested_quantity": 10,
                "budget": 100000,
                "deadline_days": 5,
                "price_flexibility": "Sometimes",
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

import unittest

from fastapi.testclient import TestClient

from backend.ai_app import app
from backend.main import load_locked_data


class LiveDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.sku = load_locked_data()["catalog_skus"][0]

    def test_live_decision_accepts_valid_fresh_request(self):
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
        self.assertEqual(body["mode"], "LIVE_REQUEST")
        self.assertIn(body["decision"], {"ACCEPT", "NEGOTIATE", "REJECT"})
        self.assertGreaterEqual(body["candidate_count"], body["survivor_count"])
        self.assertEqual(body["risk_gate_rejections"], body["candidate_count"] - body["survivor_count"])
        self.assertTrue(body["evidence_status"].startswith("FRESH_DETERMINISTIC"))

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

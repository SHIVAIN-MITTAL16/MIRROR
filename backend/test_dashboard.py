import unittest
from math import isfinite

from fastapi.testclient import TestClient

from backend.main import APP, load_dashboard_artifacts


class MerchantDashboardTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.client = TestClient(APP)
		cls.artifacts = load_dashboard_artifacts()

	def test_dashboard_summary_matches_persisted_totals(self):
		response = self.client.get("/dashboard/summary")
		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(body["requests"], 500)
		self.assertEqual(body["negotiate"], 55)
		self.assertEqual(body["risk_gate_rejections"], 2477)
		self.assertEqual(len(self.client.get("/dashboard/requests").json()), 500)
		metrics = self.client.get("/dashboard/product-metrics").json()
		self.assertAlmostEqual(metrics["mean_seed_uplift"], 0.112874768982505, places=12)
		self.assertEqual(metrics["price_candidates"], 1248)

	def test_seed_metrics_and_request_explorer_are_persisted(self):
		self.assertEqual(self.client.get("/dashboard/seeds").status_code, 200)
		response = self.client.get("/dashboard/request/20260821/1")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["decision"], self.artifacts["requests"][(20260821, 1)])

	def test_unknown_explorer_request_is_not_found(self):
		self.assertEqual(self.client.get("/dashboard/request/20260821/101").status_code, 404)

	def test_optional_incoming_eta_serializes_as_null_without_changing_finite_values(self):
		response = self.client.get("/dashboard/request/20260823/40")
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertIsNone(payload["buyer_request"]["incoming_eta_days"])
		self.assertAlmostEqual(payload["buyer_request"]["q_raw"], 23.435981340442858, places=12)

		def assert_json_finite(value):
			if isinstance(value, dict):
				for nested in value.values():
					assert_json_finite(nested)
			elif isinstance(value, list):
				for nested in value:
					assert_json_finite(nested)
			elif isinstance(value, float):
				self.assertTrue(isfinite(value))

		assert_json_finite(payload)

	def test_experimental_merchant_ledger_is_not_a_payment_surface(self):
		self.assertEqual(self.client.post("/payments/create-order", json={}).status_code, 404)
		self.assertEqual(self.client.post("/payments/verify", json={}).status_code, 404)


if __name__ == "__main__":
	unittest.main()

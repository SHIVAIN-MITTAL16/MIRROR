import os
import unittest
from math import isfinite

from fastapi.testclient import TestClient

from backend.main import APP, PAYMENT_ORDERS, candidate_amount_paise, load_dashboard_artifacts


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

	def test_selected_candidate_and_amount_are_persisted(self):
		for (seed, request_id), record in self.artifacts["requests"].items():
			if record["decision"] == "NEGOTIATE":
				candidate = record["best_candidate"]
				self.assertIn(candidate, record["candidates"])
				self.assertEqual(candidate_amount_paise(candidate), round(candidate["candidate_price"] * candidate["quantity"] * 100))
				return
		self.fail("Expected at least one persisted negotiated request")

	def test_payment_boundary_is_disabled_without_credentials(self):
		old_id, old_secret = os.environ.pop("RAZORPAY_KEY_ID", None), os.environ.pop("RAZORPAY_KEY_SECRET", None)
		try:
			response = self.client.post("/payments/create-order", json={"seed": 20260821, "request_id": 1})
			self.assertEqual(response.status_code, 503)
			self.assertNotIn("key_secret", response.text)
			invalid = self.client.post("/payments/verify", json={"razorpay_order_id": "nope", "razorpay_payment_id": "pay", "razorpay_signature": "bad"})
			self.assertEqual(invalid.status_code, 503)
		finally:
			if old_id is not None:
				os.environ["RAZORPAY_KEY_ID"] = old_id
			if old_secret is not None:
				os.environ["RAZORPAY_KEY_SECRET"] = old_secret

	def test_non_selected_candidate_cannot_create_order_and_invalid_signature_is_rejected(self):
		old_id, old_secret = os.environ.get("RAZORPAY_KEY_ID"), os.environ.get("RAZORPAY_KEY_SECRET")
		os.environ["RAZORPAY_KEY_ID"] = "rzp_test_dashboard"
		os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
		try:
			response = self.client.post("/payments/create-order", json={"seed": 20260821, "request_id": 1})
			self.assertEqual(response.status_code, 409)
			PAYMENT_ORDERS["order_test"] = {"verified": False, "payment_id": None}
			response = self.client.post("/payments/verify", json={
				"razorpay_order_id": "order_test", "razorpay_payment_id": "pay_test",
				"razorpay_signature": "invalid",
			})
			self.assertEqual(response.status_code, 400)
		finally:
			PAYMENT_ORDERS.pop("order_test", None)
			if old_id is None:
				os.environ.pop("RAZORPAY_KEY_ID", None)
			else:
				os.environ["RAZORPAY_KEY_ID"] = old_id
			if old_secret is None:
				os.environ.pop("RAZORPAY_KEY_SECRET", None)
			else:
				os.environ["RAZORPAY_KEY_SECRET"] = old_secret


if __name__ == "__main__":
	unittest.main()

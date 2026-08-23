import unittest

from backend.main import buyer_total_ceiling, build_decision_candidates, build_baseline_reference


class BaselineReferenceTests(unittest.TestCase):
	def test_baseline_reference_is_exempt_from_buyer_total_ceiling(self):
		request = {
			"target_sku_id": "LAP-007", "requested_quantity": 17,
			"deadline_days": 5, "budget": 391025.77561255335,
			"price_tolerance_pct": 0.02, "baseline_feasible": True,
			"quantity_tolerance_pct": 0.10, "timing_tolerance_days": 0,
			"eligible_substitute_skus": [],
		}
		reference = build_baseline_reference(request)
		self.assertEqual(reference["candidate_price"] * reference["quantity"], 456450)
		self.assertGreater(reference["candidate_price"] * reference["quantity"], buyer_total_ceiling(request))
		self.assertEqual(reference["action_type"], "BASELINE")
		for candidate in build_decision_candidates(request):
			self.assertLessEqual(candidate["candidate_price"] * candidate["quantity"], buyer_total_ceiling(request))


if __name__ == "__main__":
	unittest.main()

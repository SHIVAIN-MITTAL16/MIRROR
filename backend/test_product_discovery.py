import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.ai_app import APP


class ProductDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(APP)

    def test_unconfigured_adapter_reports_configuration_required(self):
        with patch.dict(os.environ, {"CHANNEL3_API_KEY": ""}, clear=False):
            self.assertEqual(self.client.get("/api/products/config").json(), {
                "configured": False, "provider": "Channel3",
            })
            response = self.client.post("/api/products/search", json={"query": "laptop"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["required_environment"], ["CHANNEL3_API_KEY"])

    def test_search_uses_documented_server_side_api_and_preserves_unknowns(self):
        provider_response = {"next_page_token": None, "products": [{
            "id": "product-1", "title": "Example Laptop", "brands": ["Example"],
            "structured_attributes": {"ram": ["16 GB"], "model": ["Example 14"]},
            "offers": [{"domain": "shop.example", "price": {"value": "900", "currency_code": "USD"}, "url": "https://shop.example/item"}],
        }]}
        with patch.dict(os.environ, {"CHANNEL3_API_KEY": "test-key"}), \
             patch("backend.product_discovery._channel3_request", return_value=provider_response) as provider:
            result = self.client.post("/api/products/search", json={"query": "laptop", "limit": 4})
        self.assertEqual(result.status_code, 200, result.text)
        row = result.json()["products"][0]
        self.assertEqual(row["brand"], "Example")
        self.assertEqual(row["model"], "Example 14")
        self.assertEqual(row["structured_attributes"]["ram"], ["16 GB"])
        self.assertEqual(row["source"], "Channel3")
        self.assertTrue(row["retrieved_at"])
        provider.assert_called_once_with("/v1/search", "POST", {"query": "laptop", "limit": 4})

    def test_search_rejects_extra_fields(self):
        response = self.client.post("/api/products/search", json={"query": "laptop", "api_key": "never"})
        self.assertEqual(response.status_code, 422)

    def test_ambiguous_brand_and_model_are_left_unknown(self):
        from backend.product_discovery import _product_row

        row = _product_row({
            "id": "multi-brand-product", "title": "Example device",
            "brands": ["Example", "Other"],
            "structured_attributes": {"model": ["Model A", "Model B"]},
        })
        self.assertIsNone(row["brand"])
        self.assertIsNone(row["model"])


if __name__ == "__main__":
    unittest.main()

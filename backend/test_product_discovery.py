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
        provider_response = {"items": [{
            "id": "product-1", "title": "Example Laptop", "brand": "Example",
            "structured_attributes": {"ram": ["16 GB"]},
            "offers": [{"domain": "shop.example", "price": {"value": "900", "currency_code": "USD"}, "url": "https://shop.example/item"}],
        }]}
        with patch.dict(os.environ, {"CHANNEL3_API_KEY": "test-key"}), \
             patch("backend.product_discovery._channel3_request", return_value=provider_response) as provider:
            result = self.client.post("/api/products/search", json={"query": "laptop", "limit": 4})
        self.assertEqual(result.status_code, 200, result.text)
        row = result.json()["products"][0]
        self.assertEqual(row["brand"], "Example")
        self.assertIsNone(row["model"])
        self.assertEqual(row["structured_attributes"]["ram"], ["16 GB"])
        self.assertEqual(row["source"], "Channel3")
        self.assertTrue(row["retrieved_at"])
        provider.assert_called_once_with("/v1/search", "POST", {"query": "laptop", "limit": 4})

    def test_search_rejects_extra_fields(self):
        response = self.client.post("/api/products/search", json={"query": "laptop", "api_key": "never"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

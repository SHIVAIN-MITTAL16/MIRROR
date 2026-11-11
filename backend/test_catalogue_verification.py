import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.test_auth_client import AuthenticatedTestClient

from backend.main import APP
from backend.passports import connect, initialize_database


class Channel3CatalogueVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(Path(self.temp_dir.name) / "catalogue.sqlite3")
        initialize_database()
        self.client = AuthenticatedTestClient(APP)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self.old_path is None:
            os.environ.pop("MIRROR_DATABASE_PATH", None)
        else:
            os.environ["MIRROR_DATABASE_PATH"] = self.old_path
        self.temp_dir.cleanup()

    def create_passport(self, extra_conditions=None):
        conditions = [
            {"condition_type": "brand", "operator": "eq", "expected_value": "Example",
             "unit": None, "hard_or_soft": "hard", "supporting_quote": "Example"},
            {"condition_type": "model", "operator": "eq", "expected_value": "Model X",
             "unit": None, "hard_or_soft": "hard", "supporting_quote": "Model X"},
            {"condition_type": "ram", "operator": "gte", "expected_value": "16",
             "unit": "GB", "hard_or_soft": "hard", "supporting_quote": "at least 16 GB RAM"},
        ]
        conditions.extend(extra_conditions or [])
        buyer_intent = "Example Model X; at least 16 GB RAM. " + " ".join(
            item["supporting_quote"] for item in (extra_conditions or [])
        )
        response = self.client.post("/api/passports/confirm-intent", json={
            "buyer_intent": buyer_intent,
            "currency": "USD", "buyer_acknowledged": True, "conditions": conditions,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_offer(self, passport, *, title="Example Model X laptop", seller_values=None, confirmed=True):
        conditions = []
        for condition in passport["conditions"]:
            supplied_values = seller_values or {}
            conditions.append({
                "condition_id": condition["id"],
                "seller_confirms": confirmed,
                "seller_value": supplied_values.get(condition["id"], supplied_values.get(condition["condition_type"], {
                    "brand": "Example", "model": "Model X", "ram": "16 GB",
                    "item_condition": "new",
                }.get(condition["condition_type"], condition["expected_value"]))),
                "evidence_content": "SYNTHETIC TEST ONLY: seller declaration.",
            })
        response = self.client.post(f"/api/passports/{passport['id']}/offers", json={
            "product_name": title, "seller_name": "Declared seller", "displayed_price": 100,
            "currency": "USD", "conditions": conditions,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    @staticmethod
    def product(**overrides):
        result = {
            "id": "channel3-product-1",
            "title": "Example Model X laptop",
            "brands": ["Example"],
            "structured_attributes": {
                "model": ["Model X"], "ram": ["16 GB"],
                "storage-capacity": ["512 GB"], "processor-family": ["Example Core 7"],
                "display-resolution": ["1920 x 1080"], "operating-system": ["ExampleOS"],
            },
            "offers": [],
        }
        result.update(overrides)
        return result

    def verify(self, passport, offer, product=None, *, product_id="channel3-product-1"):
        with patch("backend.catalogue_verification._channel3_request", return_value=product or self.product()) as provider:
            response = self.client.post(
                f"/api/passports/{passport['id']}/offers/{offer['id']}/catalogue-verification",
                json={"product_id": product_id},
            )
        return response, provider

    def test_matching_identity_brand_model_and_ram_are_audited_as_scoped_claims(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        response, provider = self.verify(passport, offer)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "verified")
        self.assertEqual(body["assurance_category"], "independently_verified_catalogue_fact")
        self.assertTrue(body["identity_matches_offer"])
        self.assertEqual({item["condition_type"] for item in body["condition_results"] if item["status"] == "verified"}, {"brand", "model", "ram"})
        provider.assert_called_once_with("/v1/products/channel3-product-1", "GET")
        with connect() as db:
            evidence = db.execute("SELECT * FROM evidence_items WHERE id=?", (body["evidence_id"],)).fetchone()
            claims = db.execute("SELECT claim_type,claim_value,unit FROM evidence_claims WHERE evidence_id=?", (body["evidence_id"],)).fetchall()
            event = db.execute("SELECT * FROM evidence_verification_events WHERE event_id=(SELECT verification_event_id FROM evidence_claims WHERE evidence_id=? LIMIT 1)", (body["evidence_id"],)).fetchone()
            links = db.execute("SELECT condition_id,claim_id FROM condition_evidence WHERE evidence_id=?", (body["evidence_id"],)).fetchall()
        self.assertEqual(evidence["source_name"], "Channel3")
        self.assertEqual(evidence["source_reference"], "channel3-product-1")
        self.assertEqual(evidence["source_classification"], "server_source")
        self.assertEqual(evidence["content_type"], "application/json")
        self.assertEqual(evidence["lifecycle_state"], "verified")
        self.assertEqual({(row["claim_type"], row["claim_value"], row["unit"]) for row in claims}, {
            ("brand", "Example", None), ("model", "Model X", None), ("ram", "16", "GB"),
        })
        self.assertTrue(event["verifier_identity"])
        self.assertTrue(event["verifier_version"])
        self.assertIn("fulfilment", event["does_not_prove_json"])
        self.assertEqual(len(links), 6)  # each scoped claim is linked to its buyer and seller condition
        decision = self.client.post(f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}").json()
        self.assertEqual(decision["outcome"], "APPROVE")
        evidence_read = self.client.get(f"/api/passports/{passport['id']}/evidence/{body['evidence_id']}").json()
        self.assertEqual(evidence_read["assurance_category"], "independently_verified_catalogue_fact")

    def test_incorrect_catalogue_identity_creates_no_claim_and_escalates(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        response, _ = self.verify(passport, offer, self.product(title="Different product"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "identity_mismatch")
        self.assertFalse(response.json()["identity_matches_offer"])
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence_claims WHERE evidence_id=?", (response.json()["evidence_id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM condition_evidence WHERE evidence_id=?", (response.json()["evidence_id"],)).fetchone()[0], 0)
        decision = self.client.post(f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}").json()
        self.assertEqual(decision["outcome"], "ESCALATE")

    def test_seller_catalogue_spec_conflict_remains_unresolved(self):
        passport = self.create_passport()
        offer = self.create_offer(passport, seller_values={"ram": "32 GB"})
        response, _ = self.verify(passport, offer, self.product())
        self.assertEqual(response.status_code, 200)
        ram = next(item for item in response.json()["condition_results"] if item["condition_type"] == "ram")
        self.assertEqual(ram["status"], "conflicting")
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence_claims WHERE evidence_id=? AND claim_type='ram'", (response.json()["evidence_id"],)).fetchone()[0], 0)
        decision = self.client.post(f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}").json()
        self.assertEqual(decision["outcome"], "ESCALATE")

    def test_unconfirmed_seller_condition_does_not_create_a_catalogue_claim(self):
        passport = self.create_passport()
        offer = self.create_offer(passport, confirmed=False)
        response, _ = self.verify(passport, offer)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(item["status"] == "verified" for item in response.json()["condition_results"]))
        self.assertTrue(all(
            item["reason"] == "seller_condition_not_confirmed"
            for item in response.json()["condition_results"]
        ))
        with connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM evidence_claims WHERE evidence_id=?",
                (response.json()["evidence_id"],),
            ).fetchone()[0], 0)

    def test_claim_is_not_inferred_for_an_unassociated_same_type_condition(self):
        extra = [{
            "condition_type": "ram", "operator": "gte", "expected_value": "16",
            "unit": "GB", "hard_or_soft": "hard", "supporting_quote": "at least 16 GB RAM",
        }]
        passport = self.create_passport(extra)
        ram_conditions = [item for item in passport["conditions"] if item["condition_type"] == "ram"]
        offer = self.create_offer(passport, seller_values={ram_conditions[1]["id"]: "8 GB"})
        response, _ = self.verify(passport, offer)
        self.assertEqual(response.status_code, 200, response.text)
        results = {item["condition_id"]: item for item in response.json()["condition_results"]}
        self.assertEqual(results[ram_conditions[0]["id"]]["status"], "verified")
        self.assertEqual(results[ram_conditions[1]["id"]]["status"], "conflicting")
        duplicate = self.client.post(
            f"/api/passports/{passport['id']}/offers/{offer['id']}/catalogue-verification",
            json={"product_id": "channel3-product-1"},
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        duplicate_results = {item["condition_id"]: item for item in duplicate.json()["condition_results"]}
        self.assertEqual(duplicate_results[ram_conditions[0]["id"]]["status"], "verified")
        self.assertEqual(duplicate_results[ram_conditions[1]["id"]]["status"], "unsupported")
        decision = self.client.post(f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}").json()
        unresolved = {item["condition_id"] for item in decision["unresolved_conditions"]}
        self.assertIn(ram_conditions[1]["id"], unresolved)
        self.assertNotIn(ram_conditions[1]["id"], {item["condition_id"] for item in decision["passed_conditions"]})

    def test_missing_attributes_and_unsupported_item_condition_stay_unresolved(self):
        extra = [{"condition_type": "item_condition", "operator": "eq", "expected_value": "new",
                  "unit": None, "hard_or_soft": "hard", "supporting_quote": "Example"}]
        passport = self.create_passport(extra)
        offer = self.create_offer(passport)
        product = self.product(structured_attributes={"ram": [], "storage-capacity": []})
        response, _ = self.verify(passport, offer, product)
        self.assertEqual(response.status_code, 200)
        results = {item["condition_type"]: item for item in response.json()["condition_results"]}
        self.assertEqual(results["ram"]["status"], "unsupported")
        self.assertEqual(results["model"]["status"], "unsupported")
        self.assertEqual(results["item_condition"]["reason"], "unsupported_claim_type")
        self.assertEqual(len(response.json()["condition_results"]), 4)

    def test_capacity_unit_mismatch_is_not_converted(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        response, _ = self.verify(passport, offer, self.product(structured_attributes={
            "model": ["Model X"], "ram": ["16 GiB"],
        }))
        self.assertEqual(response.status_code, 200)
        ram = next(item for item in response.json()["condition_results"] if item["condition_type"] == "ram")
        self.assertEqual(ram["status"], "unsupported")
        self.assertEqual(ram["reason"], "catalogue_unit_mismatch_no_conversion_performed")

    def test_stale_provider_record_is_preserved_unverified_without_claims(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        response, _ = self.verify(passport, offer, self.product(updated_at=old))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["catalogue_source_timestamp_status"], "stale_source_data")
        with connect() as db:
            row = db.execute("SELECT lifecycle_state FROM evidence_items WHERE id=?", (response.json()["evidence_id"],)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM evidence_claims WHERE evidence_id=?", (response.json()["evidence_id"],)).fetchone()[0]
        self.assertEqual(row["lifecycle_state"], "unverified")
        self.assertEqual(count, 0)

    def test_verified_catalogue_snapshot_ages_out_and_cannot_support_decision(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        real_datetime = datetime

        class OldClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime.now(tz) - timedelta(days=45)

        # Simulate an old server retrieval timestamp while the provider omits
        # its own update timestamp, as in the live response.
        with patch("backend.catalogue_verification.datetime", OldClock):
            response, _ = self.verify(passport, offer)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "verified")
        decision = self.client.post(
            f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}"
        ).json()
        self.assertEqual(decision["outcome"], "ESCALATE")
        unresolved_types = {item["condition_type"] for item in decision["unresolved_conditions"]}
        self.assertTrue({"brand", "model", "ram"}.issubset(unresolved_types))
        self.assertTrue(all(
            "evidence_stale" in item["reasons"]
            for item in decision["unresolved_conditions"]
            if item["condition_type"] in {"brand", "model", "ram"}
        ))

    def test_provider_failure_has_no_partial_evidence_or_claims(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        with patch("backend.catalogue_verification._channel3_request", side_effect=HTTPException(502, "Channel3 request failed (HTTP 503).")):
            response = self.client.post(
                f"/api/passports/{passport['id']}/offers/{offer['id']}/catalogue-verification",
                json={"product_id": "channel3-product-1"},
            )
        self.assertEqual(response.status_code, 502)
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence_items WHERE evidence_type='channel3_product_catalogue'").fetchone()[0], 0)

    def test_missing_passport_invalid_offer_wrong_product_and_malformed_response_fail_closed(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        missing_passport = self.client.post(
            "/api/passports/missing-passport/offers/missing-offer/catalogue-verification",
            json={"product_id": "channel3-product-1"},
        )
        invalid_offer = self.client.post(
            f"/api/passports/{passport['id']}/offers/missing-offer/catalogue-verification",
            json={"product_id": "channel3-product-1"},
        )
        self.assertEqual(missing_passport.status_code, 404)
        self.assertEqual(invalid_offer.status_code, 404)

        wrong_product, _ = self.verify(passport, offer, self.product(id="another-product"))
        self.assertEqual(wrong_product.status_code, 502)
        malformed, _ = self.verify(passport, offer, {"product": ["not an object"]}, product_id="malformed")
        self.assertEqual(malformed.status_code, 502)
        with connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM evidence_items WHERE evidence_type='channel3_product_catalogue'"
            ).fetchone()[0], 0)

    def test_duplicate_attempt_is_idempotent_and_wrong_scope_is_rejected(self):
        passport = self.create_passport()
        offer = self.create_offer(passport)
        first, provider = self.verify(passport, offer)
        duplicate, _ = self.verify(passport, offer)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(first.json()["evidence_id"], duplicate.json()["evidence_id"])
        provider.assert_called_once()
        foreign = self.create_passport()
        foreign_offer = self.create_offer(foreign)
        wrong_passport = self.client.post(
            f"/api/passports/{passport['id']}/offers/{foreign_offer['id']}/catalogue-verification",
            json={"product_id": "channel3-product-1"},
        )
        self.assertEqual(wrong_passport.status_code, 404)
        wrong_condition_payload = self.client.post(
            f"/api/passports/{passport['id']}/offers/{offer['id']}/catalogue-verification",
            json={"product_id": "channel3-product-2", "condition_ids": ["foreign-condition"]},
        )
        self.assertEqual(wrong_condition_payload.status_code, 422)


if __name__ == "__main__":
    unittest.main()

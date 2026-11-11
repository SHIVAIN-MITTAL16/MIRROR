import os
import json
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request as URLRequest

from fastapi.testclient import TestClient
from backend.test_auth_client import AuthenticatedTestClient

from backend.ai_app import APP
from backend.passports import connect, initialize_database
from backend.passport_decision import PassportDecision
from backend import paypal


class SyntheticTestVerifier:
    """Test-only verifier for synthetic seller declarations; absent from runtime modules."""

    IDENTITY = "test-only:SyntheticTestVerifier"
    VERSION = "unittest-1"

    @classmethod
    def verify_offer_evidence(cls, evidence_id, condition_type, condition_value, unit):
        """Create separate, labelled synthetic evidence with explicit claim links."""
        with connect() as db:
            evidence = db.execute("""
                SELECT lifecycle_state,is_simulated,source_classification,offer_snapshot_id,
                       passport_id,captured_value
                FROM evidence_items WHERE id=?
            """, (evidence_id,)).fetchone()
            if (evidence is None or evidence["lifecycle_state"] != "raw"
                    or evidence["is_simulated"] or evidence["source_classification"] != "client_submitted"
                    or not evidence["offer_snapshot_id"]):
                raise AssertionError("test verifier accepts only raw, non-simulated synthetic offer evidence")
            seller_condition = db.execute("""
                SELECT id,buyer_condition_id FROM purchase_conditions
                WHERE owner='merchant' AND offer_snapshot_id=?
            """, (evidence["offer_snapshot_id"],)).fetchone()
            if seller_condition is None:
                raise AssertionError("synthetic verifier requires a persisted seller condition")
            synthetic_id = f"synthetic-{evidence_id}"
            ingestion_event_id = f"test-ingest-{evidence_id}"
            event_id = f"test-verify-{evidence_id}"
            recorded_at = "2026-01-01T00:00:00+00:00"
            proves = [{"type": condition_type, "value": str(condition_value), "unit": unit}]
            db.execute("""
                INSERT INTO evidence_items
                (id,passport_id,evidence_type,source_name,captured_value,verification_status,
                 captured_at,is_simulated,original_content,content_type,received_at,
                 source_classification,content_sha256,offer_snapshot_id,lifecycle_state)
                VALUES(?,?, 'synthetic_test_only', ?, ?, 'unverified', ?, 0, ?,
                       'text/plain', ?, 'server_source', ?, ?, 'raw')
            """, (synthetic_id, evidence["passport_id"], cls.IDENTITY,
                  str(condition_value), recorded_at, str(condition_value), recorded_at,
                  f"synthetic-test-digest-{synthetic_id}", evidence["offer_snapshot_id"]))
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,from_state,to_state,actor_type,actor_reference,
                 method,recorded_at,proves_json,does_not_prove_json,reason)
                VALUES(?,?,NULL,'raw','system',?,'synthetic_test_ingestion',?,'[]',?,'Test-only synthetic fixture.')
            """, (ingestion_event_id, synthetic_id, evidence["offer_snapshot_id"], recorded_at,
                  json.dumps(["This synthetic fixture does not establish real-world product or seller facts."])))
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,from_state,to_state,actor_type,actor_reference,
                 verifier_identity,verifier_version,method,recorded_at,proves_json,
                 does_not_prove_json,reason)
                VALUES(?,?,'raw','verified','server_verifier',?,?,?, 'synthetic_test_fixture',?,?,?,?)
            """, (
                event_id, synthetic_id, evidence["offer_snapshot_id"], cls.IDENTITY,
                cls.VERSION, recorded_at,
                json.dumps(proves),
                json.dumps(["seller identity", "source authenticity", "future delivery or fulfilment"]),
                "Test-only deterministic synthetic evidence; not a production verification.",
            ))
            db.execute("""
                UPDATE evidence_items SET lifecycle_state='verified',verification_status='verified'
                WHERE id=?
            """, (synthetic_id,))
            db.execute("""
                INSERT INTO evidence_claims
                (claim_id,evidence_id,verification_event_id,claim_type,claim_value,unit,created_at)
                VALUES(?,?,?,?,?,?,?)
            """, (
                f"test-claim-{evidence_id}", synthetic_id, event_id, condition_type,
                str(condition_value), unit, recorded_at,
            ))
            for condition_id in (seller_condition["buyer_condition_id"], seller_condition["id"]):
                db.execute("""
                    INSERT INTO condition_evidence(condition_id,evidence_id,claim_id)
                    VALUES(?,?,?)
                """, (condition_id, synthetic_id, f"test-claim-{evidence_id}"))


class SellerOfferAndPayPalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(Path(self.temp_dir.name) / "test.sqlite3")
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

    def make_passport(self):
        response = self.client.post("/api/passports/confirm-intent", json={
            "buyer_intent": "A new item under 100 USD.",
            "currency": "USD",
            "buyer_acknowledged": True,
            "conditions": [{
                "condition_type": "price", "operator": "lte", "expected_value": "100",
                "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "under 100 USD",
            }],
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def seller_offer_payload(self, passport):
        condition = passport["conditions"][0]
        return {
            "product_name": "Demo product",
            "seller_name": "Demo seller",
            "displayed_price": 120,
            "currency": "USD",
            "conditions": [{
                "condition_id": condition["id"],
                "seller_confirms": False,
                "seller_value": "120",
                "evidence_content": "Seller declaration: price is 120 USD.",
            }],
        }

    def test_paypal_oauth_builds_expected_urllib_request(self):
        class FakeResponse:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return json.dumps({"access_token": "mock-access-token"}).encode()

        config = {
            "client_id": "mock-client-id",
            "client_secret": "mock-client-secret",
            "base_url": "https://api-m.sandbox.paypal.com",
            "configured": True,
        }
        with patch("backend.paypal.urlopen", return_value=FakeResponse()) as request_call:
            token = paypal._request_access_token(config)

        self.assertEqual(token, "mock-access-token")
        request = request_call.call_args.args[0]
        self.assertIsInstance(request, URLRequest)
        self.assertEqual(request.full_url, "https://api-m.sandbox.paypal.com/v1/oauth2/token")
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertEqual(request_call.call_args.kwargs["timeout"], 45)

    def test_synthetic_test_verifier_supports_real_approve_and_paypal_order_gate(self):
        passport_response = self.client.post("/api/passports/confirm-intent", json={
            "buyer_intent": "A camera under 150 USD.",
            "currency": "USD",
            "buyer_acknowledged": True,
            "conditions": [{
                "condition_type": "price", "operator": "lte", "expected_value": "150",
                "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "under 150 USD",
            }],
        })
        self.assertEqual(passport_response.status_code, 201, passport_response.text)
        passport = passport_response.json()
        offer_payload = self.seller_offer_payload(passport)
        offer_payload["conditions"][0].update({"seller_confirms": True, "seller_value": "120"})
        offer = self.client.post(
            f"/api/passports/{passport['id']}/offers", json=offer_payload
        )
        self.assertEqual(offer.status_code, 201, offer.text)
        offer = offer.json()
        seller_condition = offer["conditions"][0]
        self.assertTrue(seller_condition["merchant_confirmed"])
        evidence = seller_condition["evidence"][0]
        self.assertEqual(evidence["lifecycle_state"], "raw")
        self.assertEqual(evidence["source_classification"], "client_submitted")

        SyntheticTestVerifier.verify_offer_evidence(
            evidence["id"], "price", "120", "USD"
        )
        evaluation = self.client.post(
            f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}"
        )
        self.assertEqual(evaluation.status_code, 200, evaluation.text)
        self.assertEqual(evaluation.json()["outcome"], "APPROVE", evaluation.text)
        self.assertEqual(len(evaluation.json()["passed_conditions"]), 2)

        provider_order = {
            "id": "ORDER-TEST-APPROVED", "status": "CREATED",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "120.00"}}],
        }
        with patch.dict(os.environ, {
            "PAYPAL_CLIENT_ID": "test-id", "PAYPAL_CLIENT_SECRET": "test-secret",
        }), patch("backend.paypal.create_paypal_order", return_value=provider_order) as provider:
            response = self.client.post(
                f"/api/passports/{passport['id']}/paypal/order", json={"offer_id": offer["id"]}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["order_id"], "ORDER-TEST-APPROVED")
        provider.assert_called_once()

    def test_seller_offer_persists_raw_evidence_and_evaluation_escalates(self):
        passport = self.make_passport()
        response = self.client.post(
            f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)
        )
        self.assertEqual(response.status_code, 201, response.text)
        offer = response.json()
        self.assertEqual(len(offer["conditions"]), 1)
        seller_condition = offer["conditions"][0]
        self.assertEqual(seller_condition["owner"], "merchant")
        self.assertFalse(seller_condition["merchant_confirmed"])
        self.assertEqual(seller_condition["evidence"][0]["lifecycle_state"], "raw")
        self.assertEqual(seller_condition["evidence"][0]["verification_status"], "unverified")
        self.assertEqual(seller_condition["evidence"][0]["source_classification"], "client_submitted")

        decision = self.client.post(
            f"/api/passports/{passport['id']}/evaluate?offer_id={offer['id']}"
        )
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertEqual(decision.json()["outcome"], "ESCALATE")
        self.assertTrue(decision.json()["unresolved_conditions"])

    def test_simulated_demo_evidence_stays_simulated(self):
        passport = self.make_passport()
        payload = self.seller_offer_payload(passport)
        payload["conditions"][0]["is_simulated"] = True
        payload["conditions"][0]["seller_confirms"] = True
        response = self.client.post(f"/api/passports/{passport['id']}/offers", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        evidence = response.json()["conditions"][0]["evidence"][0]
        self.assertTrue(evidence["is_simulated"])
        self.assertEqual(evidence["lifecycle_state"], "simulated")
        self.assertEqual(evidence["verification_status"], "simulated")

    def test_dispute_record_tracks_buyer_condition_and_existing_evidence(self):
        passport = self.make_passport()
        condition_id = passport["conditions"][0]["id"]
        evidence = self.client.post(f"/api/passports/{passport['id']}/evidence", json={
            "content": "Synthetic buyer report evidence.", "content_type": "text/plain",
            "condition_ids": [condition_id],
        })
        self.assertEqual(evidence.status_code, 201, evidence.text)
        report = self.client.post(f"/api/passports/{passport['id']}/disputes", json={
            "condition_id": condition_id,
            "summary": "The item received does not match the promised price record.",
            "evidence_ids": [evidence.json()["id"]],
        })
        self.assertEqual(report.status_code, 201, report.text)
        self.assertEqual(report.json()["status"], "open")
        self.assertEqual(report.json()["evidence"][0]["verification_status"], "unverified")
        self.assertEqual(self.client.get(f"/api/passports/{passport['id']}/disputes").json()[0]["id"], report.json()["id"])

    def test_checkout_is_blocked_when_persisted_decision_is_not_approve(self):
        passport = self.make_passport()
        offer_response = self.client.post(
            f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)
        )
        offer = offer_response.json()
        with patch.dict(os.environ, {
            "PAYPAL_CLIENT_ID": "test-client-id",
            "PAYPAL_CLIENT_SECRET": "test-client-secret",
        }, clear=False), patch("backend.paypal.create_paypal_order") as provider:
            forged = self.client.post(
                f"/api/passports/{passport['id']}/paypal/order",
                json={"offer_id": offer["id"], "outcome": "APPROVE"},
            )
            response = self.client.post(
                f"/api/passports/{passport['id']}/paypal/order", json={"offer_id": offer["id"]}
            )
        self.assertEqual(forged.status_code, 422, forged.text)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["outcome"], "ESCALATE")
        provider.assert_not_called()

    def test_paypal_order_service_validates_provider_amount_and_currency(self):
        provider_order = {
            "id": "ORDER-123",
            "status": "CREATED",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "12.50"}}],
        }
        with patch.dict(os.environ, {
            "PAYPAL_CLIENT_ID": "test-client-id",
            "PAYPAL_CLIENT_SECRET": "test-client-secret",
        }, clear=False), patch("backend.paypal._authorized_request", return_value=provider_order) as request:
            result = paypal.create_paypal_order("12.50", "USD", "request-1")
        self.assertEqual(result["id"], "ORDER-123")
        request.assert_called_once()

    def test_paypal_currency_allowlist_rejects_inr_for_orders(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as raised:
            paypal._amount_for_offer(100, "INR")
        self.assertEqual(raised.exception.status_code, 422)

    def test_public_config_never_returns_paypal_secret_and_reports_webhook_setup(self):
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "public-id", "PAYPAL_CLIENT_SECRET": "secret", "PAYPAL_WEBHOOK_ID": "webhook-id"}, clear=False):
            payload = self.client.get("/api/paypal/config").json()
        self.assertTrue(payload["configured"])
        self.assertTrue(payload["webhook_configured"])
        self.assertEqual(payload["client_id"], "public-id")
        self.assertNotIn("client_secret", payload)
        self.assertNotIn("secret", str(payload))

    def test_paypal_webhook_rejects_invalid_signature(self):
        event = {"id": "EVENT-BAD", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}}
        headers = {
            "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api-m.sandbox.paypal.com/cert",
            "paypal-transmission-id": "tx-1", "paypal-transmission-sig": "invalid",
            "paypal-transmission-time": "2026-11-09T00:00:00Z",
        }
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret", "PAYPAL_WEBHOOK_ID": "wh-id"}), \
             patch("backend.paypal._authorized_request", return_value={"verification_status": "FAILURE"}):
            response = self.client.post("/api/paypal/webhooks", json=event, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid PayPal webhook signature")

    def test_verified_paypal_capture_webhook_reconciles_idempotently(self):
        passport = self.make_passport()
        offer = self.client.post(f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)).json()
        with connect() as db:
            db.execute("""UPDATE purchase_passports SET paypal_order_id='ORDER-WEBHOOK',paypal_status='created',
                paypal_offer_snapshot_id=?,paypal_amount='120.00',paypal_currency='USD' WHERE id=?""",
                       (offer["id"], passport["id"]))
        event = {"id": "EVENT-OK", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
            "id": "CAPTURE-WEBHOOK", "status": "COMPLETED",
            "amount": {"value": "120.00", "currency_code": "USD"},
            "supplementary_data": {"related_ids": {"order_id": "ORDER-WEBHOOK"}},
        }}
        headers = {
            "paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api-m.sandbox.paypal.com/cert",
            "paypal-transmission-id": "tx-2", "paypal-transmission-sig": "signed",
            "paypal-transmission-time": "2026-11-09T00:00:00Z",
        }
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "id", "PAYPAL_CLIENT_SECRET": "secret", "PAYPAL_WEBHOOK_ID": "wh-id"}), \
             patch("backend.paypal._authorized_request", return_value={"verification_status": "SUCCESS"}):
            response = self.client.post("/api/paypal/webhooks", json=event, headers=headers)
            duplicate = self.client.post("/api/paypal/webhooks", json=event, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["processed"])
        self.assertTrue(duplicate.json()["duplicate"])
        with connect() as db:
            row = db.execute("SELECT paypal_status,paypal_capture_id FROM purchase_passports WHERE id=?", (passport["id"],)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM paypal_webhook_events WHERE event_id='EVENT-OK'").fetchone()[0]
        self.assertEqual(tuple(row), ("captured", "CAPTURE-WEBHOOK"))
        self.assertEqual(count, 1)

    @staticmethod
    def approved(passport_id):
        return PassportDecision(
            passport_id=passport_id, outcome="APPROVE", passed_conditions=[],
            failed_conditions=[], unresolved_conditions=[], reasons=[],
        )

    def test_approved_order_creation_is_persisted_and_duplicate_is_idempotent(self):
        passport = self.make_passport()
        offer = self.client.post(
            f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)
        ).json()
        provider_order = {
            "id": "ORDER-TEST-123", "status": "CREATED",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "120.00"}}],
        }
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "test-id", "PAYPAL_CLIENT_SECRET": "test-secret"}), \
             patch("backend.paypal.evaluate_passport_state", side_effect=lambda db, pid, oid: self.approved(pid)), \
             patch("backend.paypal.create_paypal_order", return_value=provider_order) as provider:
            path = f"/api/passports/{passport['id']}/paypal/order"
            response = self.client.post(path, json={"offer_id": offer["id"]})
            self.assertEqual(response.status_code, 200, response.text)
            duplicate = self.client.post(path, json={"offer_id": offer["id"]})
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["order_id"], "ORDER-TEST-123")
        provider.assert_called_once()
        with connect() as db:
            stored = db.execute("SELECT paypal_status,paypal_amount,paypal_currency FROM purchase_passports WHERE id=?", (passport["id"],)).fetchone()
        self.assertEqual(tuple(stored), ("created", "120.00", "USD"))

    def test_capture_rechecks_decision_and_repeated_capture_is_safe(self):
        passport = self.make_passport()
        offer = self.client.post(
            f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)
        ).json()
        with connect() as db:
            db.execute("""
                UPDATE purchase_passports
                SET paypal_order_id='ORDER-CAPTURE-1',paypal_status='created',
                    paypal_offer_snapshot_id=?,paypal_amount='120.00',paypal_currency='USD'
                WHERE id=?
            """, (offer["id"], passport["id"]))
        remote_order = {
            "id": "ORDER-CAPTURE-1", "status": "APPROVED",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "120.00"}}],
        }
        captured = {
            "id": "ORDER-CAPTURE-1", "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [{
                "id": "CAPTURE-1", "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "120.00"},
            }]}}],
        }
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "test-id", "PAYPAL_CLIENT_SECRET": "test-secret"}), \
             patch("backend.paypal.evaluate_passport_state", side_effect=lambda db, pid, oid: self.approved(pid)), \
             patch("backend.paypal.get_paypal_order", return_value=remote_order), \
             patch("backend.paypal.capture_paypal_order", return_value=captured) as provider:
            response = self.client.post(
                f"/api/passports/{passport['id']}/paypal/capture", json={"order_id": "ORDER-CAPTURE-1"}
            )
            duplicate = self.client.post(
                f"/api/passports/{passport['id']}/paypal/capture", json={"order_id": "ORDER-CAPTURE-1"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["capture_id"], "CAPTURE-1")
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["status"], "COMPLETED")
        provider.assert_called_once()

    def _capture_fixture(self, passport, offer, status):
        order_id = f"ORDER-{status}"
        with connect() as db:
            db.execute("""UPDATE purchase_passports SET paypal_order_id=?,paypal_status='created',
                paypal_offer_snapshot_id=?,paypal_amount='120.00',paypal_currency='USD' WHERE id=?""",
                       (order_id, offer["id"], passport["id"]))
        remote_order = {"id": order_id, "status": "APPROVED",
                        "purchase_units": [{"amount": {"currency_code": "USD", "value": "120.00"}}]}
        capture = {"id": order_id, "status": status, "purchase_units": [{"payments": {"captures": [{
            "id": f"CAPTURE-{status}", "status": status,
            "amount": {"currency_code": "USD", "value": "120.00"},
        }]}}]}
        with patch.dict(os.environ, {"PAYPAL_CLIENT_ID": "test-id", "PAYPAL_CLIENT_SECRET": "test-secret"}), \
             patch("backend.paypal.evaluate_passport_state", side_effect=lambda db, pid, oid: self.approved(pid)), \
             patch("backend.paypal.get_paypal_order", return_value=remote_order), \
             patch("backend.paypal.capture_paypal_order", return_value=capture):
            response = self.client.post(f"/api/passports/{passport['id']}/paypal/capture", json={"order_id": order_id})
        with connect() as db:
            stored = db.execute("SELECT paypal_status,paypal_capture_id FROM purchase_passports WHERE id=?", (passport["id"],)).fetchone()
        return response, tuple(stored)

    def test_pending_capture_is_persisted_without_claiming_success(self):
        passport = self.make_passport()
        offer = self.client.post(f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)).json()
        response, stored = self._capture_fixture(passport, offer, "PENDING")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "PENDING")
        self.assertEqual(stored, ("pending", "CAPTURE-PENDING"))

    def test_declined_capture_is_persisted_without_claiming_success(self):
        passport = self.make_passport()
        offer = self.client.post(f"/api/passports/{passport['id']}/offers", json=self.seller_offer_payload(passport)).json()
        response, stored = self._capture_fixture(passport, offer, "DECLINED")
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["status"], "DECLINED")
        self.assertEqual(stored, ("declined", None))


if __name__ == "__main__":
    unittest.main()

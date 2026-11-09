import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import APP
from backend.passports import initialize_database


@contextmanager
def sqlite_connection(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class EvidenceIngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_database_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "evidence.sqlite3")
        cls.client = TestClient(APP)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        if cls.old_database_path is None:
            os.environ.pop("MIRROR_DATABASE_PATH", None)
        else:
            os.environ["MIRROR_DATABASE_PATH"] = cls.old_database_path
        cls.temp_dir.cleanup()

    def create_passport(self):
        response = self.client.post("/api/passports", json={
            "buyer_intent": "A product matching the confirmed conditions",
            "currency": "USD",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def add_condition(self, passport_id, owner="buyer", condition_type="price", expected="20"):
        response = self.client.post(f"/api/passports/{passport_id}/conditions", json=[{
            "owner": owner,
            "condition_type": condition_type,
            "operator": "eq",
            "expected_value": expected,
            "hard_or_soft": "hard",
            "buyer_confirmed": owner == "buyer",
            "merchant_confirmed": owner == "merchant",
        }])
        self.assertEqual(response.status_code, 201, response.text)
        matching_conditions = [
            condition for condition in response.json()
            if condition["owner"] == owner
            and condition["condition_type"] == condition_type
            and condition["expected_value"] == expected
        ]
        self.assertEqual(len(matching_conditions), 1, response.text)
        return matching_conditions[0]["id"]

    def ingest(self, passport_id, **overrides):
        body = {
            "content": "Advertised price: 20 USD",
            "content_type": "text/plain",
        }
        body.update(overrides)
        return self.client.post(f"/api/passports/{passport_id}/evidence", json=body)

    def test_raw_ingestion_stores_server_digest_provenance_and_unverified_state(self):
        passport_id = self.create_passport()
        content = "Price shown: £25.50"
        response = self.ingest(
            passport_id,
            content=content,
            claimed_source_name="Seller listing (user claim)",
            claimed_source_reference="https://shop.invalid/product/123",
            claimed_captured_at="2020-01-01T00:00:00Z",
            description="Text copied from a listing page",
        )
        self.assertEqual(response.status_code, 201, response.text)
        evidence = response.json()
        self.assertEqual(evidence["original_content"], None)
        self.assertEqual(evidence["lifecycle_state"], "raw")
        self.assertEqual(evidence["verification_status"], "unverified")
        self.assertFalse(evidence["is_simulated"])
        self.assertEqual(evidence["source_classification"], "client_submitted")
        self.assertEqual(evidence["claimed_source_name"], "Seller listing (user claim)")
        self.assertEqual(evidence["claimed_captured_at"], "2020-01-01T00:00:00Z")
        self.assertEqual(evidence["content_sha256"], hashlib.sha256(content.encode("utf-8")).hexdigest())
        self.assertTrue(evidence["received_at"].endswith("+00:00"))
        self.assertNotEqual(evidence["received_at"], evidence["claimed_captured_at"])
        self.assertEqual(evidence["claims"], [])
        self.assertEqual(evidence["verification_history"][0]["to_state"], "raw")
        self.assertIn("Source authenticity has not been verified.", evidence["limitations"])

    def test_content_type_and_utf8_payload_limits(self):
        passport_id = self.create_passport()
        self.assertEqual(self.ingest(passport_id, content_type="text/html").status_code, 422)
        self.assertEqual(self.ingest(passport_id, content_type="application/octet-stream").status_code, 422)
        self.assertEqual(self.ingest(passport_id, content="x" * (64 * 1024 + 1)).status_code, 422)
        self.assertEqual(self.ingest(passport_id, content="é" * 32769).status_code, 422)
        self.assertEqual(self.ingest(passport_id, content_type="application/json", content="not json").status_code, 422)

    def test_trusted_fields_are_rejected_and_urls_are_not_fetched(self):
        passport_id = self.create_passport()
        for field, value in (
            ("verification_status", "verified"),
            ("lifecycle_state", "verified"),
            ("verifier_identity", "trusted"),
            ("claims", [{"claim_type": "price", "claim_value": "20"}]),
            ("content_sha256", "forged"),
            ("received_at", "2000-01-01T00:00:00Z"),
            ("is_simulated", False),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.ingest(passport_id, **{field: value}).status_code, 422)
        response = self.ingest(passport_id, claimed_source_reference="http://127.0.0.1:1/private")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["claimed_source_reference"], "http://127.0.0.1:1/private")
        self.assertEqual(response.json()["verification_status"], "unverified")

    def test_retrieval_hides_content_by_default_and_returns_links_claims_and_history(self):
        passport_id = self.create_passport()
        condition_id = self.add_condition(passport_id)
        response = self.ingest(passport_id, condition_ids=[condition_id])
        self.assertEqual(response.status_code, 201, response.text)
        evidence_id = response.json()["id"]

        listing = self.client.get(f"/api/passports/{passport_id}/evidence")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["original_content"], None)
        self.assertEqual(listing.json()[0]["associated_conditions"][0]["condition_id"], condition_id)
        self.assertEqual(listing.json()[0]["claims"], [])
        self.assertTrue(listing.json()[0]["verification_history"])

        detail = self.client.get(f"/api/passports/{passport_id}/evidence/{evidence_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIsNone(detail.json()["original_content"])
        content = self.client.get(f"/api/passports/{passport_id}/evidence/{evidence_id}?include_content=true")
        self.assertEqual(content.json()["original_content"], "Advertised price: 20 USD")

    def test_evidence_links_to_multiple_conditions_and_rejects_cross_passport_ids(self):
        passport_id = self.create_passport()
        price_condition = self.add_condition(passport_id, condition_type="price")
        second_price_condition = self.add_condition(passport_id, owner="merchant", condition_type="price")
        self.assertNotEqual(price_condition, second_price_condition)

        persisted_conditions = self.client.get(f"/api/passports/{passport_id}").json()["conditions"]
        persisted_ids = {condition["id"] for condition in persisted_conditions}
        self.assertTrue({price_condition, second_price_condition}.issubset(persisted_ids))

        response = self.ingest(passport_id, condition_ids=[price_condition, second_price_condition])
        self.assertEqual(response.status_code, 201, response.text)
        linked_condition_ids = {
            item["condition_id"] for item in response.json()["associated_conditions"]
        }
        self.assertEqual(linked_condition_ids, {price_condition, second_price_condition})

        other_passport = self.create_passport()
        foreign_condition = self.add_condition(other_passport)
        rejected = self.ingest(passport_id, condition_ids=[foreign_condition])
        self.assertEqual(rejected.status_code, 422)

    def test_unverified_content_does_not_pass_and_price_claim_cannot_prove_delivery(self):
        passport_id = self.create_passport()
        buyer_condition = self.add_condition(passport_id, condition_type="delivery_days", expected="3")
        response = self.ingest(passport_id, condition_ids=[buyer_condition])
        self.assertEqual(response.status_code, 201, response.text)
        evidence = response.json()
        decision = self.client.post(f"/api/passports/{passport_id}/evaluate").json()
        self.assertEqual(decision["outcome"], "ESCALATE")
        self.assertTrue(any(item["condition_id"] == buyer_condition for item in decision["unresolved_conditions"]))

        # Simulate a server verifier that establishes only a price claim. Even
        # verified price evidence cannot satisfy a delivery-time condition.
        database = os.environ["MIRROR_DATABASE_PATH"]
        with sqlite_connection(database) as db:
            trusted_evidence_id = "trusted-price-evidence"
            event_id, claim_id = "verified-price-event", "verified-price-claim"
            db.execute("""
                INSERT INTO evidence_items
                (id,passport_id,evidence_type,source_name,captured_value,verification_status,
                 captured_at,is_simulated,original_content,content_type,received_at,
                 source_classification,content_sha256,lifecycle_state)
                VALUES(?,?,'trusted_listing','test_verifier','20','verified',
                       '2026-01-01T00:00:00Z',0,'Price shown: 20','text/plain',
                       '2026-01-01T00:00:00Z','server_source','test-digest','verified')
            """, (trusted_evidence_id, passport_id))
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,to_state,actor_type,method,recorded_at,proves_json,does_not_prove_json,reason)
                VALUES(?,?,'verified','server_verifier','test_scope','2026-01-01T00:00:00Z',?,?,?)
            """, (event_id, trusted_evidence_id, json.dumps([{"type": "price", "value": "20"}]),
                  json.dumps(["Delivery timing was not established."]), "Test verifier scope"))
            db.execute("""
                INSERT INTO evidence_claims
                (claim_id,evidence_id,verification_event_id,claim_type,claim_value,created_at)
                VALUES(?,?,?,'price','20','2026-01-01T00:00:00Z')
            """, (claim_id, trusted_evidence_id, event_id))
            db.execute("""
                INSERT INTO condition_evidence(condition_id,evidence_id,claim_id)
                VALUES(?,?,?)
            """, (buyer_condition, trusted_evidence_id, claim_id))
        decision = self.client.post(f"/api/passports/{passport_id}/evaluate").json()
        unresolved = next(item for item in decision["unresolved_conditions"] if item["condition_id"] == buyer_condition)
        self.assertIn("evidence_scope_mismatch", unresolved["reasons"])
        self.assertEqual(decision["outcome"], "ESCALATE")

    def test_verification_history_is_append_only(self):
        passport_id = self.create_passport()
        evidence_id = self.ingest(passport_id).json()["id"]
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            event_id = db.execute(
                "SELECT event_id FROM evidence_verification_events WHERE evidence_id=?", (evidence_id,)
            ).fetchone()[0]
        for statement in (
            "UPDATE evidence_verification_events SET reason='changed' WHERE event_id=?",
            "DELETE FROM evidence_verification_events WHERE event_id=?",
        ):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
                    db.execute(statement, (event_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
                db.execute("UPDATE evidence_items SET original_content='changed' WHERE id=?", (evidence_id,))

        # Existing claims use the same database-level append-only policy.
        condition_id = self.add_condition(passport_id)
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            trusted_evidence_id = "append-only-claim-evidence"
            verified_event_id = "append-only-claim-event"
            claim_id = "append-only-claim"
            db.execute("""
                INSERT INTO evidence_items
                (id,passport_id,evidence_type,source_name,captured_value,verification_status,
                 captured_at,is_simulated,lifecycle_state)
                VALUES(?,?,'test','test','20','verified','2026-01-01T00:00:00Z',0,'verified')
            """, (trusted_evidence_id, passport_id))
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,to_state,actor_type,method,recorded_at,proves_json,reason)
                VALUES(?,?,'verified','server_verifier','test','2026-01-01T00:00:00Z',?, 'test fixture')
            """, (verified_event_id, trusted_evidence_id,
                  json.dumps([{"type": "price", "value": "20"}])))
            db.execute("""
                INSERT INTO evidence_claims
                (claim_id,evidence_id,verification_event_id,claim_type,claim_value,created_at)
                VALUES(?,?,?,'price','20','2026-01-01T00:00:00Z')
            """, (claim_id, trusted_evidence_id, verified_event_id))
        with self.assertRaises(sqlite3.IntegrityError):
            with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
                db.execute("""
                    INSERT INTO evidence_claims
                    (claim_id,evidence_id,verification_event_id,claim_type,claim_value,created_at)
                    VALUES('out-of-scope-claim',?,?,'delivery_days','3','2026-01-01T00:00:00Z')
                """, (trusted_evidence_id, verified_event_id))
        for statement in (
            "UPDATE evidence_claims SET claim_value='21' WHERE claim_id=?",
            "DELETE FROM evidence_claims WHERE claim_id=?",
        ):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
                    db.execute(statement, (claim_id,))

    def test_associations_are_immutable_after_insertion(self):
        passport_id = self.create_passport()
        condition_id = self.add_condition(passport_id)
        second_condition_id = self.add_condition(
            passport_id, owner="merchant", condition_type="price"
        )
        evidence_id = self.ingest(passport_id, condition_ids=[condition_id]).json()["id"]

        for statement, parameters in (
            ("UPDATE condition_evidence SET condition_id=? WHERE condition_id=? AND evidence_id=?",
             (second_condition_id, condition_id, evidence_id)),
            ("DELETE FROM condition_evidence WHERE condition_id=? AND evidence_id=?",
             (condition_id, evidence_id)),
        ):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
                    db.execute(statement, parameters)

        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            self.assertEqual(db.execute(
                "SELECT condition_id FROM condition_evidence WHERE evidence_id=?", (evidence_id,)
            ).fetchone()[0], condition_id)

    def test_evidence_state_changes_require_a_matching_audit_event(self):
        passport_id = self.create_passport()
        evidence_id = self.ingest(passport_id).json()["id"]
        attempts = (
            "UPDATE evidence_items SET lifecycle_state='verified' WHERE id=?",
            "UPDATE evidence_items SET verification_status='verified' WHERE id=?",
            "UPDATE evidence_items SET lifecycle_state='verified', verification_status='verified' WHERE id=?",
        )
        for statement in attempts:
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
                    db.execute(statement, (evidence_id,))
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            row = db.execute(
                "SELECT lifecycle_state,verification_status FROM evidence_items WHERE id=?", (evidence_id,)
            ).fetchone()
            self.assertEqual(tuple(row), ("raw", "unverified"))

    def test_legacy_evidence_and_relationship_migrate_without_claims(self):
        db_path = Path(self.temp_dir.name) / "legacy-evidence.sqlite3"
        passport_id, condition_id, evidence_id = "legacy-p", "legacy-c", "legacy-e"
        with sqlite_connection(db_path) as db:
            db.executescript("""
                CREATE TABLE purchase_passports (
                    id TEXT PRIMARY KEY,status TEXT NOT NULL,buyer_intent TEXT NOT NULL,
                    currency TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,paypal_order_id TEXT
                );
                CREATE TABLE purchase_conditions (
                    id TEXT PRIMARY KEY,passport_id TEXT NOT NULL,condition_type TEXT NOT NULL,
                    operator TEXT NOT NULL,expected_value TEXT NOT NULL,unit TEXT,
                    hard_or_soft TEXT NOT NULL,buyer_confirmed INTEGER NOT NULL DEFAULT 0,
                    evidence_status TEXT NOT NULL DEFAULT 'unverified', owner TEXT NOT NULL DEFAULT 'buyer',
                    merchant_confirmed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE evidence_items (
                    id TEXT PRIMARY KEY,passport_id TEXT NOT NULL,evidence_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,source_reference TEXT,captured_value TEXT NOT NULL,
                    verification_status TEXT NOT NULL,captured_at TEXT NOT NULL,
                    is_simulated INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE condition_evidence (
                    condition_id TEXT NOT NULL,evidence_id TEXT NOT NULL,
                    PRIMARY KEY(condition_id,evidence_id)
                );
            """)
            db.execute("INSERT INTO purchase_passports VALUES(?,?,?,?,?,?,?)", (
                passport_id,"draft","Legacy","USD","2026-01-01Z","2026-01-01Z",None,
            ))
            db.execute("INSERT INTO purchase_conditions VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                condition_id,passport_id,"price","eq","20",None,"hard",1,"supported","buyer",0,
            ))
            db.execute("INSERT INTO evidence_items VALUES(?,?,?,?,?,?,?,?,?)", (
                evidence_id,passport_id,"listing","legacy","user-reference","20","verified","2026-01-01Z",0,
            ))
            db.execute("INSERT INTO condition_evidence VALUES(?,?)", (condition_id,evidence_id))

        previous_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(db_path)
        try:
            initialize_database()
            initialize_database()
            with sqlite_connection(db_path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM condition_evidence").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT lifecycle_state FROM evidence_items WHERE id=?", (evidence_id,)).fetchone()[0], "unverified")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence_verification_events WHERE evidence_id=?", (evidence_id,)).fetchone()[0], 1)
            decision = self.client.post(f"/api/passports/{passport_id}/evaluate").json()
        finally:
            if previous_path is None:
                os.environ.pop("MIRROR_DATABASE_PATH", None)
            else:
                os.environ["MIRROR_DATABASE_PATH"] = previous_path
        self.assertEqual(decision["outcome"], "ESCALATE")
        condition_result = next(item for item in decision["unresolved_conditions"] if item["condition_id"] == condition_id)
        self.assertIn("evidence_missing_or_unlinked", condition_result["reasons"])


if __name__ == "__main__":
    unittest.main()

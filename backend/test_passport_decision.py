import os
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import APP


@contextmanager
def sqlite_connection(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class PassportDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_database_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "decision.sqlite3")
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
            "buyer_intent": "A sealed camera delivered by the agreed date",
            "currency": "USD",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def add_condition(self, passport_id, owner, condition_type="item_condition", expected="sealed", hard_or_soft="hard", confirmed=True, operator="eq"):
        body = {
            "owner": owner,
            "condition_type": condition_type,
            "operator": operator,
            "expected_value": expected,
            "hard_or_soft": hard_or_soft,
            "buyer_confirmed": confirmed if owner == "buyer" else False,
            "merchant_confirmed": confirmed if owner == "merchant" else False,
        }
        response = self.client.post(f"/api/passports/{passport_id}/conditions", json=[body])
        self.assertEqual(response.status_code, 201, response.text)
        condition_id = response.json()[-1]["id"]
        # The public condition API deliberately ignores client confirmation flags.
        # Decision fixtures model previously confirmed records directly in SQLite.
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            if confirmed and owner == "buyer":
                db.execute(
                    "UPDATE purchase_conditions SET buyer_confirmed = 1, buyer_confirmed_at = ? WHERE id = ?",
                    ("2026-01-01T00:00:00+00:00", condition_id),
                )
            elif confirmed and owner == "merchant":
                db.execute("UPDATE purchase_conditions SET merchant_confirmed = 1 WHERE id = ?", (condition_id,))
        return condition_id

    def add_evidence(self, passport_id, condition_id, value, status="verified", simulated=False):
        evidence_id = f"e-{condition_id}-{value}-{status}-{int(simulated)}"
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            condition_type = db.execute(
                "SELECT condition_type FROM purchase_conditions WHERE id = ?", (condition_id,)
            ).fetchone()[0]
            verification_state = "verified" if status == "verified" and not simulated else (
                "simulated" if simulated else "unverified"
            )
            lifecycle_state = "simulated" if simulated else verification_state
            db.execute("""
                INSERT INTO evidence_items
                (id, passport_id, evidence_type, source_name, source_reference,
                 captured_value, verification_status, captured_at, is_simulated,
                 original_content,content_type,received_at,source_classification,
                 content_sha256,lifecycle_state)
                VALUES (?, ?, 'listing_field', 'test_fixture', NULL, ?, ?,
                        '2026-01-01T00:00:00+00:00', ?, ?, 'text/plain',
                        '2026-01-01T00:00:00+00:00', 'server_source', 'fixture', ?)
            """, (
                evidence_id, passport_id, str(value), status, int(simulated),
                str(value), lifecycle_state,
            ))
            event_id = f"event-{evidence_id}"
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,to_state,actor_type,method,recorded_at,
                 proves_json,does_not_prove_json,reason)
                VALUES(?,?,?,'server_verifier','test_fixture',?,?, '[]','test setup')
            """, (
                event_id, evidence_id, verification_state, "2026-01-01T00:00:00+00:00",
                json.dumps([{"type": condition_type, "value": str(value)}])
                if verification_state == "verified" else "[]",
            ))
            claim_id = None
            if verification_state == "verified":
                claim_id = f"claim-{evidence_id}"
                db.execute("""
                    INSERT INTO evidence_claims
                    (claim_id,evidence_id,verification_event_id,claim_type,claim_value,created_at)
                    VALUES(?,?,?,?,?,?)
                """, (
                    claim_id, evidence_id, event_id, condition_type, str(value),
                    "2026-01-01T00:00:00+00:00",
                ))
            db.execute(
                "INSERT INTO condition_evidence(condition_id, evidence_id, claim_id) VALUES (?, ?, ?)",
                (condition_id, evidence_id, claim_id),
            )
        return evidence_id

    def create_two_sided_conditions(self, buyer_value="sealed", merchant_value="Camera", *, buyer_hard="hard", merchant_hard="hard", merchant_type="product_name", buyer_confirmed=True, merchant_confirmed=True):
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected=buyer_value, hard_or_soft=buyer_hard, confirmed=buyer_confirmed)
        merchant_id = self.add_condition(passport_id, "merchant", condition_type=merchant_type, expected=merchant_value, hard_or_soft=merchant_hard, confirmed=merchant_confirmed)
        self.add_evidence(passport_id, buyer_id, buyer_value)
        self.add_evidence(passport_id, merchant_id, merchant_value)
        return passport_id, buyer_id, merchant_id

    def evaluate(self, passport_id):
        response = self.client.post(f"/api/passports/{passport_id}/evaluate")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_approve_requires_both_confirmed_sides_and_verified_evidence(self):
        passport_id, _, _ = self.create_two_sided_conditions()
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "APPROVE")
        self.assertEqual({item["owner"] for item in result["passed_conditions"]}, {"buyer", "merchant"})
        self.assertEqual(result["failed_conditions"], [])
        self.assertEqual(result["unresolved_conditions"], [])
        self.assertFalse(result["ml_assessment"]["applied"])

    def test_verified_hard_failure_rejects_even_when_other_information_is_missing(self):
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected="sealed")
        self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera")
        self.add_evidence(passport_id, buyer_id, "opened")
        missing_evidence_id = self.add_condition(
            passport_id, "merchant", condition_type="return_terms",
            expected="30 days", hard_or_soft="hard",
        )
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "REJECT")
        self.assertTrue(any(item["owner"] == "buyer" for item in result["failed_conditions"]))
        self.assertTrue(any(
            item["condition_id"] == missing_evidence_id
            and "evidence_missing_or_unlinked" in item["reasons"]
            for item in result["unresolved_conditions"]
        ))

    def test_verified_soft_failure_negotiates(self):
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected="sealed", hard_or_soft="hard")
        merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera", hard_or_soft="soft")
        self.add_evidence(passport_id, buyer_id, "sealed")
        self.add_evidence(passport_id, merchant_id, "Different Camera")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "NEGOTIATE")
        self.assertEqual([item["owner"] for item in result["failed_conditions"]], ["merchant"])

    def test_unresolved_information_precedes_soft_negotiation(self):
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected="sealed", hard_or_soft="soft")
        merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera", hard_or_soft="soft")
        self.add_evidence(passport_id, buyer_id, "opened")
        self.add_evidence(passport_id, merchant_id, "Camera", status="unverified")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "ESCALATE")
        self.assertTrue(result["failed_conditions"])
        self.assertTrue(result["unresolved_conditions"])

    def test_missing_unverified_simulated_and_conflicting_evidence_escalate(self):
        # Missing condition link.
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer")
        self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "ESCALATE")
        self.assertIn("evidence_missing_or_unlinked", result["unresolved_conditions"][0]["reasons"])

        # Unverified and simulated evidence cannot establish a comparison.
        for status, simulated in (("unverified", False), ("unknown", False), ("verified", True)):
            with self.subTest(status=status, simulated=simulated):
                passport_id = self.create_passport()
                buyer_id = self.add_condition(passport_id, "buyer")
                merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera")
                self.add_evidence(passport_id, buyer_id, "sealed", status=status, simulated=simulated)
                self.add_evidence(passport_id, merchant_id, "Camera")
                result = self.evaluate(passport_id)
                self.assertEqual(result["outcome"], "ESCALATE")
                if simulated:
                    unresolved = next(item for item in result["unresolved_conditions"] if item["condition_id"] == buyer_id)
                    self.assertTrue(unresolved["simulated_evidence_ids"])

        # Distinct verified values on one condition are conflicting evidence.
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer")
        merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera")
        self.add_evidence(passport_id, buyer_id, "sealed")
        self.add_evidence(passport_id, buyer_id, "opened")
        self.add_evidence(passport_id, merchant_id, "Camera")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "ESCALATE")
        self.assertIn("conflicting_verified_evidence", result["unresolved_conditions"][0]["reasons"])

    def test_missing_confirmation_and_missing_party_conditions_escalate(self):
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", confirmed=False)
        self.add_evidence(passport_id, buyer_id, "sealed")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "ESCALATE")
        self.assertIn("buyer_confirmation_missing", result["unresolved_conditions"][0]["reasons"])
        self.assertTrue(any(item["owner"] == "merchant" and item["condition_id"] is None for item in result["unresolved_conditions"]))

        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected="sealed")
        merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera", confirmed=False)
        self.add_evidence(passport_id, buyer_id, "sealed")
        self.add_evidence(passport_id, merchant_id, "Camera")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "ESCALATE")
        merchant_result = next(item for item in result["unresolved_conditions"] if item["condition_id"] == merchant_id)
        self.assertEqual(merchant_result["confirmation_required"], "merchant_confirmed")
        self.assertFalse(merchant_result["confirmation_received"])

    def test_one_evidence_item_can_support_multiple_conditions(self):
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected="sealed")
        merchant_id = self.add_condition(passport_id, "merchant", condition_type="item_condition", expected="sealed")
        evidence_id = self.add_evidence(passport_id, buyer_id, "sealed")
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            claim_id = db.execute("SELECT claim_id FROM condition_evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
            db.execute("INSERT INTO condition_evidence(condition_id,evidence_id,claim_id) VALUES (?,?,?)", (merchant_id, evidence_id, claim_id))
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "APPROVE")
        self.assertEqual(len(result["passed_conditions"]), 2)
        self.assertTrue(all(item["evidence_ids"] == [evidence_id] for item in result["passed_conditions"]))

    def test_unsupported_type_and_operator_are_unresolved(self):
        for condition_type, operator in (("mood", "eq"), ("price", "approximately")):
            with self.subTest(condition_type=condition_type, operator=operator):
                passport_id = self.create_passport()
                buyer_id = self.add_condition(passport_id, "buyer", condition_type=condition_type, expected="10", operator=operator)
                merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera")
                self.add_evidence(passport_id, buyer_id, "10")
                self.add_evidence(passport_id, merchant_id, "Camera")
                result = self.evaluate(passport_id)
                self.assertEqual(result["outcome"], "ESCALATE")
                self.assertTrue(any(item["condition_id"] == buyer_id for item in result["unresolved_conditions"]))

    def test_association_rejects_cross_passport_evidence(self):
        first = self.create_passport()
        second = self.create_passport()
        condition_id = self.add_condition(first, "buyer")
        second_condition = self.add_condition(second, "buyer")
        evidence_id = self.add_evidence(second, second_condition, "sealed")
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                claim_id = db.execute("SELECT claim_id FROM condition_evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()[0]
                db.execute("INSERT INTO condition_evidence(condition_id,evidence_id,claim_id) VALUES (?,?,?)", (condition_id, evidence_id, claim_id))

    def test_legacy_unlinked_evidence_migrates_without_becoming_verified(self):
        db_path = Path(self.temp_dir.name) / "legacy-evidence.sqlite3"
        passport_id, condition_id = "legacy-passport", "legacy-condition"
        with sqlite_connection(db_path) as db:
            db.executescript("""
                CREATE TABLE purchase_passports (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, buyer_intent TEXT NOT NULL,
                    currency TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    paypal_order_id TEXT
                );
                CREATE TABLE purchase_conditions (
                    id TEXT PRIMARY KEY, passport_id TEXT NOT NULL, condition_type TEXT NOT NULL,
                    operator TEXT NOT NULL, expected_value TEXT NOT NULL, unit TEXT,
                    hard_or_soft TEXT NOT NULL, buyer_confirmed INTEGER NOT NULL DEFAULT 0,
                    evidence_status TEXT NOT NULL DEFAULT 'unverified',
                    owner TEXT NOT NULL DEFAULT 'buyer', merchant_confirmed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE evidence_items (
                    id TEXT PRIMARY KEY, passport_id TEXT NOT NULL, evidence_type TEXT NOT NULL,
                    source_name TEXT NOT NULL, source_reference TEXT, captured_value TEXT NOT NULL,
                    verification_status TEXT NOT NULL, captured_at TEXT NOT NULL
                );
            """)
            db.execute("INSERT INTO purchase_passports VALUES(?,?,?,?,?,?,?)", (
                passport_id, "draft", "Legacy", "USD", "2026-01-01Z", "2026-01-01Z", None,
            ))
            db.execute("INSERT INTO purchase_conditions VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                condition_id, passport_id, "item_condition", "eq", "sealed", None,
                "hard", 1, "supported", "buyer", 0,
            ))
            db.execute("INSERT INTO evidence_items VALUES(?,?,?,?,?,?,?,?)", (
                "legacy-evidence", passport_id, "listing", "legacy-source", None,
                "sealed", "verified", "2026-01-01Z",
            ))

        previous_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(db_path)
        try:
            from backend.passports import initialize_database
            initialize_database()
            with sqlite_connection(db_path) as db:
                migrated_evidence = db.execute("SELECT is_simulated FROM evidence_items WHERE id='legacy-evidence'").fetchone()[0]
                links = db.execute("SELECT COUNT(*) FROM condition_evidence").fetchone()[0]
            response = self.client.post(f"/api/passports/{passport_id}/evaluate")
        finally:
            if previous_path is None:
                os.environ.pop("MIRROR_DATABASE_PATH", None)
            else:
                os.environ["MIRROR_DATABASE_PATH"] = previous_path

        self.assertEqual(migrated_evidence, 1)
        self.assertEqual(links, 0)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["outcome"], "ESCALATE")
        self.assertIn("evidence_missing_or_unlinked", result["unresolved_conditions"][0]["reasons"])

    def test_ml_only_runs_with_explicit_passed_structured_features_and_can_only_escalate(self):
        passport_id = self.create_passport()
        condition_specs = [
            ("buyer", "sku_id", "LAP-007", "hard"),
            ("buyer", "quantity", "2", "hard"),
            ("buyer", "delivery_days", "5", "hard"),
            ("merchant", "item_condition", "sealed", "hard"),
        ]
        for owner, condition_type, value, hardness in condition_specs:
            condition_id = self.add_condition(passport_id, owner, condition_type=condition_type, expected=value, hard_or_soft=hardness)
            self.add_evidence(passport_id, condition_id, value)

        fake_model = SimpleNamespace(
            version="test-risk-model", threshold=0.35,
            predict_probability=lambda features: 0.9,
        )
        fake_data = {"merchant_states_by_sku": {"LAP-007": {
            "sku_id": "LAP-007", "on_hand": 10, "reserved": 0,
            "incoming_exists": False, "incoming_eta_days": None,
            "incoming_quantity": 0, "mu": 1.0, "nb_k": 2,
        }}}
        with patch("backend.risk_model.get_risk_model", return_value=fake_model), \
             patch("backend.main.load_locked_data", return_value=fake_data):
            result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "ESCALATE")
        self.assertTrue(result["ml_assessment"]["applied"])
        self.assertEqual(result["ml_assessment"]["evidence_status"], "SYNTHETIC_MODEL_ESTIMATE_NOT_EVIDENCE")
        self.assertTrue(all(item["status"] == "passed" for item in result["passed_conditions"]))

        low_risk_model = SimpleNamespace(
            version="test-risk-model", threshold=0.35,
            predict_probability=lambda features: 0.1,
        )
        with patch("backend.risk_model.get_risk_model", return_value=low_risk_model), \
             patch("backend.main.load_locked_data", return_value=fake_data):
            result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "APPROVE")
        self.assertTrue(result["ml_assessment"]["applied"])

        # A deterministic hard failure is final; an ML score cannot reverse it.
        passport_id = self.create_passport()
        buyer_id = self.add_condition(passport_id, "buyer", expected="sealed", hard_or_soft="hard")
        merchant_id = self.add_condition(passport_id, "merchant", condition_type="product_name", expected="Camera")
        self.add_evidence(passport_id, buyer_id, "opened")
        self.add_evidence(passport_id, merchant_id, "Camera")
        result = self.evaluate(passport_id)
        self.assertEqual(result["outcome"], "REJECT")
        self.assertFalse(result["ml_assessment"]["applied"])

    def test_evaluation_rejects_client_supplied_verification_data(self):
        passport_id = self.create_passport()
        response = self.client.post(
            f"/api/passports/{passport_id}/evaluate",
            json={"verification_status": "verified", "captured_value": "sealed"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

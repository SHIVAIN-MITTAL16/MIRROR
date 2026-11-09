import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from backend.main import APP
from backend.passports import ConfirmIntentRequest, confirm_reviewed_intent, initialize_database


@contextmanager
def sqlite_connection(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class PassportApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_database_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "passports.sqlite3")
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
            "buyer_intent": "A new, sealed camera with delivery by Friday",
            "currency": "USD",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_and_retrieve_passport(self):
        created = self.create_passport()
        self.assertEqual(created["status"], "draft")
        self.assertIsNone(created["paypal_order_id"])
        self.assertEqual(created["conditions"], [])
        self.assertIn("+00:00", created["created_at"])

        fetched = self.client.get(f"/api/passports/{created['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["buyer_intent"], created["buyer_intent"])
        self.assertIn(created, self.client.get("/api/passports").json())

    def test_legacy_request_creates_buyer_condition_by_default(self):
        passport = self.create_passport()
        response = self.client.post(f"/api/passports/{passport['id']}/conditions", json=[
            {
                "condition_type": "delivery_date",
                "operator": "on_or_before",
                "expected_value": "2026-11-06",
                "unit": None,
                "hard_or_soft": "hard",
            },
            {
                "condition_type": "packaging",
                "operator": "equals",
                "expected_value": "factory sealed",
                "hard_or_soft": "soft",
            },
        ])
        self.assertEqual(response.status_code, 201, response.text)
        conditions = response.json()
        self.assertEqual(len(conditions), 2)
        self.assertEqual({item["passport_id"] for item in conditions}, {passport["id"]})
        self.assertTrue(all(item["owner"] == "buyer" for item in conditions))
        self.assertTrue(all(item["buyer_confirmed"] is False for item in conditions))
        self.assertTrue(all(item["merchant_confirmed"] is False for item in conditions))
        detail = self.client.get(f"/api/passports/{passport['id']}").json()
        self.assertEqual(len(detail["conditions"]), 2)
        self.assertTrue(all(item["owner"] == "buyer" for item in detail["conditions"]))

    def test_buyer_and_merchant_conditions_have_separate_confirmation(self):
        passport = self.create_passport()
        response = self.client.post(f"/api/passports/{passport['id']}/conditions", json=[
            {
                "condition_type": "packaging",
                "operator": "equals",
                "expected_value": "factory sealed",
                "owner": "buyer",
                "hard_or_soft": "hard",
                "buyer_confirmed": True,
            },
            {
                "condition_type": "delivery_window",
                "operator": "within_days",
                "expected_value": "3",
                "owner": "merchant",
                "hard_or_soft": "soft",
                "merchant_confirmed": True,
            },
        ])
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        buyer = next(condition for condition in created if condition["owner"] == "buyer")
        merchant = next(condition for condition in created if condition["owner"] == "merchant")
        self.assertFalse(buyer["buyer_confirmed"])
        self.assertFalse(buyer["merchant_confirmed"])
        self.assertFalse(merchant["buyer_confirmed"])
        self.assertFalse(merchant["merchant_confirmed"])
        self.assertIsNone(buyer["buyer_confirmed_at"])

        detail = self.client.get(f"/api/passports/{passport['id']}").json()
        self.assertEqual(
            {condition["owner"] for condition in detail["conditions"]},
            {"buyer", "merchant"},
        )

    def test_existing_database_migrates_conditions_in_place(self):
        db_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        passport_id = "legacy-passport"
        condition_id = "legacy-condition"
        with sqlite_connection(db_path) as db:
            db.executescript("""
                CREATE TABLE purchase_passports (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'draft',
                    buyer_intent TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    paypal_order_id TEXT
                );
                CREATE TABLE purchase_conditions (
                    id TEXT PRIMARY KEY,
                    passport_id TEXT NOT NULL REFERENCES purchase_passports(id) ON DELETE CASCADE,
                    condition_type TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    expected_value TEXT NOT NULL,
                    unit TEXT,
                    hard_or_soft TEXT NOT NULL,
                    buyer_confirmed INTEGER NOT NULL DEFAULT 0,
                    evidence_status TEXT NOT NULL DEFAULT 'unverified'
                );
            """)
            db.execute(
                "INSERT INTO purchase_passports VALUES(?,?,?,?,?,?,?)",
                (passport_id, "draft", "Legacy request", "USD", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", None),
            )
            db.execute(
                "INSERT INTO purchase_conditions VALUES(?,?,?,?,?,?,?,?,?)",
                (condition_id, passport_id, "packaging", "equals", "sealed", None, "hard", 1, "unverified"),
            )

        previous_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(db_path)
        try:
            initialize_database()
            response = self.client.get(f"/api/passports/{passport_id}")
        finally:
            if previous_path is None:
                os.environ.pop("MIRROR_DATABASE_PATH", None)
            else:
                os.environ["MIRROR_DATABASE_PATH"] = previous_path

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["conditions"]), 1)
        migrated = response.json()["conditions"][0]
        self.assertEqual(migrated["id"], condition_id)
        self.assertEqual(migrated["owner"], "buyer")
        self.assertTrue(migrated["buyer_confirmed"])
        self.assertFalse(migrated["merchant_confirmed"])
        self.assertIsNone(migrated["buyer_confirmed_at"])

        with sqlite_connection(db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_passports").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_conditions").fetchone()[0], 1)

    def reviewed_payload(self, **changes):
        payload = {
            "buyer_intent": "I need a new camera under 800 USD",
            "currency": "USD",
            "buyer_acknowledged": True,
            "conditions": [{
                "condition_type": "price", "operator": "lte", "expected_value": "800",
                "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "under 800 USD",
            }, {
                "condition_type": "item_condition", "operator": "eq", "expected_value": "new",
                "unit": None, "hard_or_soft": "hard", "supporting_quote": "new camera",
            }],
        }
        payload.update(changes)
        return payload

    def test_confirm_reviewed_intent_persists_buyer_confirmed_conditions(self):
        response = self.client.post("/api/passports/confirm-intent", json=self.reviewed_payload())
        self.assertEqual(response.status_code, 201, response.text)
        passport = response.json()
        self.assertEqual(passport["buyer_intent"], "I need a new camera under 800 USD")
        self.assertEqual(len(passport["conditions"]), 2)
        for condition in passport["conditions"]:
            self.assertEqual(condition["owner"], "buyer")
            self.assertTrue(condition["buyer_confirmed"])
            self.assertFalse(condition["merchant_confirmed"])
            parsed = datetime.fromisoformat(condition["buyer_confirmed_at"])
            self.assertEqual(parsed.utcoffset(), timezone.utc.utcoffset(parsed))

    def test_confirmation_keeps_currency_on_passport_and_price_only(self):
        payload = {
            "buyer_intent": "I want a new Acme camera under 800 USD delivered within 5 days.",
            "currency": "USD",
            "buyer_acknowledged": True,
            "conditions": [
                {
                    "condition_type": "price", "operator": "lt", "expected_value": "800",
                    "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "under 800 USD",
                },
                {
                    "condition_type": "product_name", "operator": "eq", "expected_value": "camera",
                    "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "camera",
                },
                {
                    "condition_type": "item_condition", "operator": "eq", "expected_value": "new",
                    "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "new",
                },
                {
                    "condition_type": "seller_name", "operator": "eq", "expected_value": "Acme",
                    "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "Acme",
                },
                {
                    "condition_type": "delivery_days", "operator": "lte", "expected_value": "5",
                    "unit": "days", "hard_or_soft": "hard", "supporting_quote": "within 5 days",
                },
            ],
        }

        response = self.client.post("/api/passports/confirm-intent", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        passport = response.json()
        self.assertEqual(passport["currency"], "USD")
        units = {condition["condition_type"]: condition["unit"] for condition in passport["conditions"]}
        self.assertEqual(units, {
            "price": "USD",
            "product_name": None,
            "item_condition": None,
            "seller_name": None,
            "delivery_days": "days",
        })
        self.assertTrue(all(condition["buyer_confirmed"] for condition in passport["conditions"]))

    def test_regular_condition_creation_does_not_copy_passport_currency_to_nonprice_unit(self):
        passport = self.create_passport()
        response = self.client.post(f"/api/passports/{passport['id']}/conditions", json=[
            {
                "condition_type": "product_name", "operator": "eq", "expected_value": "camera",
                "unit": "USD", "hard_or_soft": "hard",
            },
            {
                "condition_type": "delivery_days", "operator": "lte", "expected_value": "5",
                "unit": "days", "hard_or_soft": "hard",
            },
        ])

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            [condition["unit"] for condition in response.json()],
            [None, "days"],
        )

    def test_registered_confirm_intent_route_binds_and_parses_request_body(self):
        app_routes = []
        for registered in APP.routes:
            if isinstance(registered, APIRoute):
                app_routes.append(registered)
            elif hasattr(registered, "effective_route_contexts"):
                app_routes.extend(
                    context.original_route
                    for context in registered.effective_route_contexts()
                    if isinstance(context.original_route, APIRoute)
                )
        routes = [route for route in app_routes
                  if route.path == "/api/passports/confirm-intent" and "POST" in route.methods]
        self.assertEqual(
            len(routes), 1,
            "confirm-intent registration: " + repr([
                (type(route).__name__, getattr(route, "path", None), getattr(route, "methods", None))
                for route in app_routes
            ]),
        )
        route = routes[0]
        self.assertIs(route.endpoint, confirm_reviewed_intent)
        self.assertEqual(len(route.dependant.body_params), 1)
        body_parameter = route.dependant.body_params[0]
        self.assertEqual(body_parameter.name, "payload")
        self.assertIs(body_parameter.field_info.annotation, ConfirmIntentRequest)
        validated = ConfirmIntentRequest.model_validate(self.reviewed_payload())
        self.assertIsInstance(validated, ConfirmIntentRequest)
        response = self.client.post("/api/passports/confirm-intent", json=self.reviewed_payload())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["buyer_intent"], self.reviewed_payload()["buyer_intent"])

    def test_confirm_reviewed_intent_rejects_invalid_requests_without_writes(self):
        cases = [
            {"conditions": [{**self.reviewed_payload()["conditions"][0], "condition_type": "mystery"}]},
            {"conditions": [{**self.reviewed_payload()["conditions"][0], "operator": "contains"}]},
            {"conditions": [{**self.reviewed_payload()["conditions"][0], "supporting_quote": "invented"}]},
            {"currency": None},
            {"conditions": [{k: v for k, v in self.reviewed_payload()["conditions"][0].items() if k != "hard_or_soft"}]},
            {"conditions": []},
            {"conditions": [{**self.reviewed_payload()["conditions"][0], "owner": "merchant"}]},
            {"conditions": [{**self.reviewed_payload()["conditions"][0], "verification_status": "verified"}]},
            {"conditions": [{**self.reviewed_payload()["conditions"][0], "expected_value": "NaN"}]},
            {
                "buyer_intent": "The price must be 800 USD and not 800 USD.",
                "conditions": [
                    {"condition_type": "price", "operator": "eq", "expected_value": "800", "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "800 USD"},
                    {"condition_type": "price", "operator": "ne", "expected_value": "800", "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "800 USD"},
                ],
            },
        ]
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            before = db.execute("SELECT COUNT(*) FROM purchase_passports").fetchone()[0]
        for change in cases:
            response = self.client.post("/api/passports/confirm-intent", json=self.reviewed_payload(**change))
            self.assertEqual(response.status_code, 422, response.text)
        with sqlite_connection(os.environ["MIRROR_DATABASE_PATH"]) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_passports").fetchone()[0], before)

    def test_confirm_reviewed_intent_rolls_back_passport_if_condition_insert_fails(self):
        db_path = os.environ["MIRROR_DATABASE_PATH"]
        with sqlite_connection(db_path) as db:
            before = db.execute("SELECT COUNT(*) FROM purchase_passports").fetchone()[0]
            conditions_before = db.execute("SELECT COUNT(*) FROM purchase_conditions").fetchone()[0]
            db.execute("""
                CREATE TRIGGER test_fail_condition_insert BEFORE INSERT ON purchase_conditions
                BEGIN SELECT RAISE(ABORT, 'forced condition insert failure'); END
            """)
        try:
            with self.assertRaises(Exception):
                self.client.post("/api/passports/confirm-intent", json=self.reviewed_payload())
        finally:
            with sqlite_connection(db_path) as db:
                db.execute("DROP TRIGGER test_fail_condition_insert")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_passports").fetchone()[0], before)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_conditions").fetchone()[0], conditions_before)

    def test_invalid_data_and_missing_parent_are_rejected(self):
        invalid_passport = self.client.post("/api/passports", json={"buyer_intent": "   ", "currency": "usd"})
        self.assertEqual(invalid_passport.status_code, 422)
        self.assertEqual(self.client.get("/api/passports/not-a-passport").status_code, 404)
        invalid_condition = self.client.post("/api/passports/not-a-passport/conditions", json=[{
            "condition_type": "delivery_date",
            "operator": "before",
            "expected_value": "Friday",
            "hard_or_soft": "maybe",
        }])
        self.assertEqual(invalid_condition.status_code, 422)
        passport_for_owner_test = self.client.post("/api/passports", json={
            "buyer_intent": "A sealed camera",
            "currency": "USD",
        })
        self.assertEqual(passport_for_owner_test.status_code, 201)
        bad_owner_condition = self.client.post(
            f"/api/passports/{passport_for_owner_test.json()['id']}/conditions",
            json=[{
                "condition_type": "packaging",
                "operator": "equals",
                "expected_value": "sealed",
                "owner": "carrier",
                "hard_or_soft": "hard",
            }],
        )
        self.assertEqual(bad_owner_condition.status_code, 422)


if __name__ == "__main__":
    unittest.main()

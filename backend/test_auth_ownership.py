import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.ai_app import APP
from backend.passports import connect, initialize_database


class AuthOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = os.environ.get("MIRROR_DATABASE_PATH")
        os.environ["MIRROR_DATABASE_PATH"] = str(Path(self.temp.name) / "auth.sqlite3")
        initialize_database()
        self.buyer_a = TestClient(APP)
        self.buyer_b = TestClient(APP)
        self.seller_a = TestClient(APP)
        self.seller_b = TestClient(APP)
        self.clients = [self.buyer_a, self.buyer_b, self.seller_a, self.seller_b]
        for client in self.clients: client.__enter__()
        self.register(self.buyer_a, "buyer-a@example.test", "buyer")
        self.register(self.buyer_b, "buyer-b@example.test", "buyer")
        self.register(self.seller_a, "seller-a@example.test", "seller")
        self.register(self.seller_b, "seller-b@example.test", "seller")
        self.seller_a_id = self.seller_a.get("/api/auth/me").json()["seller_id"]
        self.seller_b_id = self.seller_b.get("/api/auth/me").json()["seller_id"]

    def tearDown(self):
        for client in self.clients: client.__exit__(None, None, None)
        if self.old_path is None: os.environ.pop("MIRROR_DATABASE_PATH", None)
        else: os.environ["MIRROR_DATABASE_PATH"] = self.old_path
        self.temp.cleanup()

    @staticmethod
    def csrf(client):
        return {"X-Mirror-CSRF": client.cookies.get("mirror_csrf", "")}

    def register(self, client, email, role):
        response = client.post("/api/auth/register", json={
            "email": email, "password": "Long-Test-Password-2060!", "role": role,
        })
        self.assertEqual(response.status_code, 201, response.text)

    def create_passport(self, client):
        response = client.post("/api/passports/confirm-intent", headers=self.csrf(client), json={
            "buyer_intent": "A new camera under 800 USD", "currency": "USD", "buyer_acknowledged": True,
            "conditions": [{"condition_type": "price", "operator": "lte", "expected_value": "800",
                            "unit": "USD", "hard_or_soft": "hard", "supporting_quote": "under 800 USD"}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def grant(self, passport, seller, seller_id):
        response = self.buyer_a.post(f"/api/passports/{passport['id']}/seller-grants",
            headers=self.csrf(self.buyer_a), json={"seller_id": seller_id})
        self.assertEqual(response.status_code, 201, response.text)
        accepted = seller.post(f"/api/seller/grants/{response.json()['id']}/accept", headers=self.csrf(seller))
        self.assertEqual(accepted.status_code, 200, accepted.text)
        return response.json()["id"]

    def test_unauthenticated_passport_and_paypal_routes_are_denied(self):
        anonymous = TestClient(APP)
        self.assertEqual(anonymous.get("/api/passports").status_code, 401)
        self.assertEqual(anonymous.post("/api/passports/id/paypal/order", json={"offer_id": "x"}).status_code, 401)
        self.assertEqual(anonymous.post("/api/passports/id/paypal/capture", json={"order_id": "x"}).status_code, 401)

    def test_cookie_mutations_require_csrf_and_buyer_role(self):
        payload = {"buyer_intent": "A new camera under 800 USD", "currency": "USD"}
        without_csrf = self.buyer_a.post("/api/passports", json=payload)
        self.assertEqual(without_csrf.status_code, 403)
        seller_attempt = self.seller_a.post("/api/passports", headers=self.csrf(self.seller_a), json=payload)
        self.assertEqual(seller_attempt.status_code, 403)

    def test_buyer_cannot_access_another_buyers_passport_and_legacy_unowned_is_hidden(self):
        passport = self.create_passport(self.buyer_a)
        self.assertEqual(self.buyer_b.get(f"/api/passports/{passport['id']}").status_code, 404)
        self.assertNotIn(passport["id"], [item["id"] for item in self.buyer_b.get("/api/passports").json()])
        historical_id = "historical-unowned-passport"
        buyer_id = self.buyer_a.get("/api/auth/me").json()["id"]
        with connect() as db:
            db.execute("""INSERT INTO purchase_passports
                (id,status,buyer_intent,currency,created_at,updated_at,buyer_user_id)
                VALUES(?,'draft','Historical record','USD','2020-01-01T00:00:00+00:00',
                       '2020-01-01T00:00:00+00:00',NULL)""", (historical_id,))
        self.assertEqual(self.buyer_a.get(f"/api/passports/{historical_id}").status_code, 404)
        with self.assertRaises(sqlite3.IntegrityError):
            with connect() as db:
                db.execute("UPDATE purchase_passports SET buyer_user_id=? WHERE id=?", (buyer_id, historical_id))

    def test_seller_access_is_passport_scoped_and_revocation_takes_effect(self):
        passport = self.create_passport(self.buyer_a)
        grant_id = self.grant(passport, self.seller_a, self.seller_a_id)
        seller_view = self.seller_a.get(f"/api/passports/{passport['id']}/seller-view")
        self.assertEqual(seller_view.status_code, 200)
        self.assertEqual(seller_view.json()["status"], "draft")
        self.assertNotIn("buyer_intent", seller_view.json())
        shared_conditions = seller_view.json()["conditions"]
        self.assertEqual(len(shared_conditions), 1)
        self.assertEqual(shared_conditions[0]["owner"], "buyer")
        self.assertTrue(shared_conditions[0]["buyer_confirmed"])
        self.assertEqual(self.seller_b.get(f"/api/passports/{passport['id']}/seller-view").status_code, 404)
        revoke = self.buyer_a.delete(f"/api/passports/{passport['id']}/seller-grants/{grant_id}", headers=self.csrf(self.buyer_a))
        self.assertEqual(revoke.status_code, 200, revoke.text)
        self.assertEqual(self.seller_a.get(f"/api/passports/{passport['id']}/seller-view").status_code, 404)

    def test_seller_cannot_create_or_accept_another_sellers_access(self):
        passport = self.create_passport(self.buyer_a)
        response = self.seller_a.post(f"/api/passports/{passport['id']}/seller-grants",
            headers=self.csrf(self.seller_a), json={"seller_id": self.seller_a_id})
        self.assertEqual(response.status_code, 403)

    def test_seller_a_lists_only_its_own_offer_and_offer_owner_is_immutable(self):
        passport = self.create_passport(self.buyer_a)
        self.grant(passport, self.seller_a, self.seller_a_id)
        self.grant(passport, self.seller_b, self.seller_b_id)
        condition_id = passport["conditions"][0]["id"]
        def create_offer(client, name):
            return client.post(f"/api/passports/{passport['id']}/offers", headers=self.csrf(client), json={
                "product_name": "Camera", "seller_name": name, "displayed_price": 700, "currency": "USD",
                "conditions": [{"condition_id": condition_id, "seller_confirms": True, "seller_value": "700",
                                "evidence_content": "seller declaration"}],
            })
        offer_a = create_offer(self.seller_a, "Seller A")
        offer_b = create_offer(self.seller_b, "Seller B")
        self.assertEqual(offer_a.status_code, 201, offer_a.text)
        self.assertEqual(offer_b.status_code, 201, offer_b.text)
        own_offers = self.seller_a.get(f"/api/passports/{passport['id']}/offers").json()
        self.assertEqual([item["id"] for item in own_offers], [offer_a.json()["id"]])
        with connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE offer_snapshots SET seller_user_id=? WHERE id=?",
                           (offer_b.json()["seller_user_id"], offer_a.json()["id"]))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE passport_seller_grants SET seller_id=? WHERE passport_id=? AND seller_id=?",
                           (self.seller_b_id, passport["id"], self.seller_a_id))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE purchase_passports SET buyer_user_id=? WHERE id=?",
                           ("another-user", passport["id"]))

    def test_expired_session_is_rejected(self):
        passport = self.create_passport(self.buyer_a)
        token = self.buyer_a.cookies.get("mirror_session")
        import hashlib
        with connect() as db:
            db.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",
                       (hashlib.sha256(token.encode()).hexdigest(),))
        self.assertEqual(self.buyer_a.get(f"/api/passports/{passport['id']}").status_code, 401)

    def test_logout_revokes_session(self):
        passport = self.create_passport(self.buyer_a)
        response = self.buyer_a.post("/api/auth/logout", headers=self.csrf(self.buyer_a))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.buyer_a.get(f"/api/passports/{passport['id']}").status_code, 401)


if __name__ == "__main__":
    unittest.main()

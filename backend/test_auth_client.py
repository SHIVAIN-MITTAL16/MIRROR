"""Authenticated test client fixture using real buyer/seller sessions and grants."""

import re
from fastapi.testclient import TestClient


class AuthenticatedTestClient:
    def __init__(self, app):
        self.buyer = TestClient(app)
        self.seller = TestClient(app)
        self.grants = set()
        self.buyer.__enter__()
        self.seller.__enter__()
        result = self._send(self.buyer, "post", "/api/auth/register", json={
            "email": "buyer-fixture@example.test", "password": "BuyerFixturePassword#2060", "role": "buyer"})
        if result.status_code != 201:
            # Process-shared test clients may leave a prior account only if a
            # fixture reused a database; login keeps the behavior deterministic.
            self._send(self.buyer, "post", "/api/auth/login", json={
                "email": "buyer-fixture@example.test", "password": "BuyerFixturePassword#2060"})
        result = self._send(self.seller, "post", "/api/auth/register", json={
            "email": "seller-fixture@example.test", "password": "SellerFixturePassword#2060", "role": "seller"})
        if result.status_code != 201:
            self._send(self.seller, "post", "/api/auth/login", json={
                "email": "seller-fixture@example.test", "password": "SellerFixturePassword#2060"})
        self.seller_id = self.seller.get("/api/auth/me").json()["seller_id"]

    @staticmethod
    def _csrf(client):
        return client.cookies.get("mirror_csrf", "")

    def _send(self, client, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        if method.lower() not in {"get", "head", "options"}:
            headers.setdefault("X-Mirror-CSRF", self._csrf(client))
        return getattr(client, method)(url, headers=headers, **kwargs)

    def _prepare_seller_grant(self, passport_id):
        if passport_id in self.grants:
            return
        grant = self._send(self.buyer, "post", f"/api/passports/{passport_id}/seller-grants",
                           json={"seller_id": self.seller_id})
        if grant.status_code == 201:
            accepted = self._send(self.seller, "post", f"/api/seller/grants/{grant.json()['id']}/accept")
            if accepted.status_code == 200:
                self.grants.add(passport_id)

    def get(self, url, **kwargs):
        client = self.seller if url.startswith("/api/seller/") or url.endswith("/seller-view") else self.buyer
        return self._send(client, "get", url, **kwargs)

    def post(self, url, **kwargs):
        match = re.match(r"^/api/passports/([^/]+)/offers$", url)
        if match:
            self._prepare_seller_grant(match.group(1))
            return self._send(self.seller, "post", url, **kwargs)
        client = self.seller if url.startswith("/api/seller/") else self.buyer
        return self._send(client, "post", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._send(self.buyer, "delete", url, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.buyer.__exit__(exc_type, exc, tb)
        self.seller.__exit__(exc_type, exc, tb)

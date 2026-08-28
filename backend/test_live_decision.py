from fastapi.testclient import TestClient

from backend.ai_app import app
from backend.main import load_locked_data


client = TestClient(app)


def test_live_decision_accepts_valid_fresh_request():
    sku = load_locked_data()["catalog_skus"][0]
    response = client.post(
        "/ai/live-decision",
        json={
            "sku_id": sku["sku_id"],
            "requested_quantity": 10,
            "budget": sku["current_price"] * 10,
            "deadline_days": 5,
            "price_flexibility": "Medium",
            "quantity_flexibility": "Medium",
            "timing_flexibility": "Medium",
            "substitution_tolerance": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "LIVE_REQUEST"
    assert body["decision"] in {"ACCEPT", "NEGOTIATE", "REJECT"}
    assert body["candidate_count"] >= body["survivor_count"]
    assert body["risk_gate_rejections"] == body["candidate_count"] - body["survivor_count"]
    assert body["evidence_status"].startswith("FRESH_DETERMINISTIC")


def test_live_decision_rejects_unknown_sku():
    response = client.post(
        "/ai/live-decision",
        json={
            "sku_id": "NOT-A-SKU",
            "requested_quantity": 10,
            "budget": 100000,
            "deadline_days": 5,
        },
    )
    assert response.status_code == 404


def test_live_decision_validates_flexibility():
    sku = load_locked_data()["catalog_skus"][0]
    response = client.post(
        "/ai/live-decision",
        json={
            "sku_id": sku["sku_id"],
            "requested_quantity": 10,
            "budget": 100000,
            "deadline_days": 5,
            "price_flexibility": "Sometimes",
        },
    )
    assert response.status_code == 422

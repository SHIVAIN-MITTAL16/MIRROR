"""AI-facing and live-decision ASGI entrypoint for MIRROR.

The original ``backend.main:app`` remains the deterministic decision engine.
This entrypoint adds the interactive live-decision surface without changing the
persisted experiment artifacts or the deterministic selection rules.

Run locally with:
    uvicorn backend.ai_app:app --host 0.0.0.0 --port 8002
"""

import hashlib
import json

from fastapi import HTTPException
from pydantic import BaseModel, Field

from backend.main import (
    APP,
    available_for_window,
    classify_buyer_request,
    eligible_substitute_skus,
    evaluate_request_decision,
    load_locked_data,
)
from backend.risk_model import get_risk_model, risk_features_for_request


class RiskPredictionRequest(BaseModel):
    sku_id: str = Field(min_length=1)
    requested_quantity: int = Field(gt=0)
    delivery_window_days: int = Field(ge=0, le=30)


class LiveDecisionRequest(BaseModel):
    sku_id: str = Field(min_length=1)
    requested_quantity: int = Field(gt=0, le=10000)
    budget: float = Field(gt=0)
    deadline_days: int = Field(ge=0, le=30)
    price_flexibility: str = Field(default="Medium")
    quantity_flexibility: str = Field(default="Medium")
    timing_flexibility: str = Field(default="Medium")
    substitution_tolerance: int = Field(default=1, ge=0, le=1)


PRICE_TOLERANCE = {"Low": 0.02, "Medium": 0.05, "High": 0.10}
QUANTITY_TOLERANCE = {"Low": 0.10, "Medium": 0.25, "High": 0.50}
TIMING_TOLERANCE = {"Low": 0, "Medium": 2, "High": 3}


def _live_request(payload: LiveDecisionRequest) -> tuple[dict, int]:
    data = load_locked_data()
    target = data["catalog_skus_by_sku"].get(payload.sku_id)
    state = data["merchant_states_by_sku"].get(payload.sku_id)
    if target is None or state is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    if payload.price_flexibility not in PRICE_TOLERANCE:
        raise HTTPException(status_code=422, detail="price_flexibility must be Low, Medium or High")
    if payload.quantity_flexibility not in QUANTITY_TOLERANCE:
        raise HTTPException(status_code=422, detail="quantity_flexibility must be Low, Medium or High")
    if payload.timing_flexibility not in TIMING_TOLERANCE:
        raise HTTPException(status_code=422, detail="timing_flexibility must be Low, Medium or High")

    flexibility = {
        "price_flexibility": payload.price_flexibility,
        "price_tolerance_pct": PRICE_TOLERANCE[payload.price_flexibility],
        "quantity_flexibility": payload.quantity_flexibility,
        "quantity_tolerance_pct": QUANTITY_TOLERANCE[payload.quantity_flexibility],
        "timing_flexibility": payload.timing_flexibility,
        "timing_tolerance_days": TIMING_TOLERANCE[payload.timing_flexibility],
        "substitution_tolerance": payload.substitution_tolerance,
    }
    substitutes = eligible_substitute_skus(
        data["catalog_skus"], payload.sku_id, target["brand"],
        target["ram_gb"], target["storage_gb"], payload.substitution_tolerance,
    )
    classification = classify_buyer_request(
        target, state, payload.requested_quantity, payload.deadline_days,
        flexibility, substitutes, data["merchant_states_by_sku"],
    )
    request = {
        "experiment_seed": 20260830,
        "request_id": 1,
        "target_sku_id": payload.sku_id,
        "brand_preference": target["brand"],
        "min_ram_gb": target["ram_gb"],
        "min_storage_gb": target["storage_gb"],
        "eligible_substitute_skus": substitutes,
        "requested_quantity": payload.requested_quantity,
        "current_price": target["current_price"],
        "budget": payload.budget,
        "deadline_days": payload.deadline_days,
        **flexibility,
        **classification,
    }

    identity = json.dumps({
        "sku_id": payload.sku_id,
        "quantity": payload.requested_quantity,
        "budget": payload.budget,
        "deadline": payload.deadline_days,
        "price_flexibility": payload.price_flexibility,
        "quantity_flexibility": payload.quantity_flexibility,
        "timing_flexibility": payload.timing_flexibility,
        "substitution_tolerance": payload.substitution_tolerance,
    }, sort_keys=True).encode()
    request["request_id"] = int.from_bytes(hashlib.sha256(identity).digest()[:4], "big")
    experiment_seed = int.from_bytes(hashlib.sha256(b"MIRROR-live-v1").digest()[:4], "big")
    request["experiment_seed"] = experiment_seed
    return request, experiment_seed


@APP.get("/ai/risk/model")
def risk_model_info():
    """Expose model provenance and held-out metrics for audit/demo purposes."""
    model = get_risk_model()
    return {
        "model_version": model.version,
        "model_type": "regularized_logistic_regression",
        "target": "SLA miss probability",
        "training_source": "locked synthetic MIRROR demand simulator",
        "evaluation_split": "SKU-held-out",
        "train_rows": model.train_rows,
        "test_rows": model.test_rows,
        "held_out_skus": list(model.test_skus),
        "threshold": model.threshold,
        "features": list(model.feature_names),
        "metrics": model.metrics,
        "evidence_status": "REPRODUCIBLE_SYNTHETIC_BENCHMARK",
    }


@APP.post("/ai/risk/predict")
def predict_risk(payload: RiskPredictionRequest):
    """Predict SLA-miss risk without changing the deterministic decision engine."""
    data = load_locked_data()
    state = data["merchant_states_by_sku"].get(payload.sku_id)
    if state is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    model = get_risk_model()
    features = risk_features_for_request(
        state,
        payload.requested_quantity,
        payload.delivery_window_days,
    )
    probability = model.predict_probability(features)
    return {
        "sku_id": payload.sku_id,
        "requested_quantity": payload.requested_quantity,
        "delivery_window_days": payload.delivery_window_days,
        "sla_miss_probability": round(probability, 6),
        "risk_level": "HIGH" if probability >= model.threshold else "LOW",
        "threshold": model.threshold,
        "model_version": model.version,
        "top_feature_contributions": model.explain(features),
        "training_source": "locked synthetic MIRROR demand simulator",
        "evidence_status": "MODEL_OUTPUT_NOT_REAL_WORLD_PERFORMANCE",
    }


@APP.post("/ai/live-decision")
def live_decision(payload: LiveDecisionRequest):
    """Evaluate a fresh user request with MIRROR's real deterministic engine."""
    request, experiment_seed = _live_request(payload)
    result = evaluate_request_decision(request, experiment_seed)
    selected = result.get("best_candidate") if result["decision"] == "NEGOTIATE" else result.get("reference") if result["decision"] == "ACCEPT" else None
    survivors = [candidate for candidate in result.get("candidates", []) if candidate.get("passes_risk_gate")]

    if result["decision"] == "NEGOTIATE":
        why = [
            "The original request was not the best safe transaction." if not request["baseline_feasible"] else "A safer alternative cleared the downside-risk gate and beat the baseline threshold.",
            f"{len(result['candidates'])} alternatives were evaluated; {len(survivors)} survived the P05 gate.",
            f"The selected {selected['action_type'].lower()} option had the highest score among safe survivors.",
        ]
    elif result["decision"] == "ACCEPT":
        why = [
            "The requested transaction is baseline-feasible.",
            f"{len(result['candidates'])} alternatives were checked, but none beat the strict improvement threshold after risk filtering.",
            "MIRROR therefore keeps the original request as the safest choice.",
        ]
    else:
        why = [
            "The requested transaction is not safely fulfillable under the current constraints.",
            f"{len(result['candidates'])} alternatives were checked and none survived the decision rule.",
            "MIRROR recommends no safe deal instead of inventing a transaction.",
        ]

    return {
        "mode": "LIVE_REQUEST",
        "evidence_status": "FRESH_DETERMINISTIC_EVALUATION_ON_LOCKED_MERCHANT_STATE",
        "buyer_request": {
            "sku_id": request["target_sku_id"],
            "quantity": request["requested_quantity"],
            "budget": request["budget"],
            "deadline_days": request["deadline_days"],
            "price_flexibility": request["price_flexibility"],
            "quantity_flexibility": request["quantity_flexibility"],
            "timing_flexibility": request["timing_flexibility"],
            "substitution_tolerance": request["substitution_tolerance"],
            "baseline_feasible": request["baseline_feasible"],
            "classification": request["classification"],
        },
        "decision": result["decision"],
        "baseline": result.get("reference"),
        "candidate_count": len(result.get("candidates", [])),
        "risk_gate_rejections": result.get("risk_gate_rejections", 0),
        "survivor_count": len(survivors),
        "selected": selected,
        "top_safe_alternatives": sorted(survivors, key=lambda item: -item.get("score", 0))[:5],
        "why": why,
        "execution": {"available": False, "reason": "Live decisions are not persisted payment orders."},
    }


@APP.get("/ai/risk/health")
def risk_health():
    """Small readiness check that also verifies the model can be loaded."""
    model = get_risk_model()
    return {"status": "ok", "model_version": model.version}


app = APP

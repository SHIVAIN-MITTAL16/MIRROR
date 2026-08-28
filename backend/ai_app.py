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
    buyer_total_ceiling,
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
        data["catalog_skus"],
        payload.sku_id,
        target["brand"],
        target["ram_gb"],
        target["storage_gb"],
        payload.substitution_tolerance,
    )

    # The persisted classifier historically treated "baseline feasible" as an
    # inventory-only concept. That is not sufficient for an interactive buyer
    # request: the buyer's budget is an explicit hard constraint. Keep the
    # persisted 500-row artifacts untouched, but make the live room honest by
    # requiring both fulfilment availability and an affordable baseline.
    availability = available_for_window(state, payload.deadline_days)
    inventory_feasible = payload.requested_quantity <= availability["available"]
    buyer_ceiling = buyer_total_ceiling({
        "budget": payload.budget,
        "price_tolerance_pct": flexibility["price_tolerance_pct"],
    })
    baseline_transaction_total = target["current_price"] * payload.requested_quantity
    budget_feasible = baseline_transaction_total <= buyer_ceiling + 1e-9

    classification = classify_buyer_request(
        target,
        state,
        payload.requested_quantity,
        payload.deadline_days,
        flexibility,
        substitutes,
        data["merchant_states_by_sku"],
    )
    baseline_feasible = inventory_feasible and budget_feasible

    if baseline_feasible:
        live_classification = classification["classification"]
    else:
        # A live request that fails either inventory or budget is a conflict if
        # the request still exposes at least one negotiation lever. The actual
        # candidate engine remains the final authority on whether a safe deal
        # exists; this label only prevents an impossible request from becoming
        # a misleading ACCEPT.
        has_budget_lever = (
            payload.price_flexibility != "Low"
            or payload.quantity_flexibility != "Low"
            or payload.timing_flexibility != "Low"
            or payload.substitution_tolerance == 1
        )
        live_classification = "CONSTRAINT_CONFLICT" if has_budget_lever else "HARD_REJECT"

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
        "baseline_feasible": baseline_feasible,
        "classification": live_classification,
        "availability": availability,
        "baseline_transaction_total": baseline_transaction_total,
        "buyer_budget_ceiling": buyer_ceiling,
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


def _competitive_alternatives(result: dict, request: dict) -> list[dict]:
    """Return only safe alternatives that are genuinely competitive.

    For a feasible baseline, an alternative must clear the exact same strict
    improvement threshold used by the decision rule. For an infeasible
    baseline, every risk-gated survivor is a legitimate recovery candidate.
    This prevents the UI from calling a merely safe-but-worse option a "top
    alternative" after MIRROR has already decided to keep the baseline.
    """
    survivors = [
        candidate
        for candidate in result.get("candidates", [])
        if candidate.get("passes_risk_gate")
    ]
    if not survivors:
        return []

    if request["baseline_feasible"]:
        reference_score = result.get("reference_score", 0)
        threshold = reference_score + 0.05 * abs(reference_score)
        survivors = [candidate for candidate in survivors if candidate.get("score", 0) > threshold]

    return sorted(
        survivors,
        key=lambda item: (-item.get("score", 0), item.get("action_type", ""), item.get("sku_id", "")),
    )[:5]


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
    selected = (
        result.get("best_candidate")
        if result["decision"] == "NEGOTIATE"
        else result.get("reference")
        if result["decision"] == "ACCEPT"
        else None
    )
    survivors = [
        candidate
        for candidate in result.get("candidates", [])
        if candidate.get("passes_risk_gate")
    ]
    alternatives = _competitive_alternatives(result, request)

    if result["decision"] == "NEGOTIATE":
        if request["baseline_feasible"]:
            why = [
                "The requested transaction is feasible, but a better safe option was found.",
                f"{len(result['candidates'])} alternatives were evaluated; {len(survivors)} survived the P05 gate.",
                f"The selected {selected['action_type'].lower()} option cleared the strict improvement threshold and scored highest among safe candidates.",
            ]
        else:
            reasons = []
            if not inventory_feasible_for_live(request):
                reasons.append("available inventory is insufficient for the requested quantity by the deadline")
            if request["baseline_transaction_total"] > request["buyer_budget_ceiling"] + 1e-9:
                reasons.append("the requested transaction exceeds the buyer's budget ceiling")
            reason_text = " and ".join(reasons) if reasons else "the original constraints could not be met"
            why = [
                f"The original request is not directly feasible because {reason_text}.",
                f"{len(result['candidates'])} alternatives were evaluated; {len(survivors)} survived the P05 gate.",
                f"MIRROR selects the highest-scoring safe recovery option: {selected['action_type'].lower()}.",
            ]
    elif result["decision"] == "ACCEPT":
        why = [
            "The requested transaction is feasible within inventory and the buyer's budget ceiling.",
            f"{len(result['candidates'])} alternatives were checked, but none beat the strict improvement threshold after risk filtering.",
            "MIRROR therefore keeps the original request as the safest choice.",
        ]
    else:
        reasons = []
        if not inventory_feasible_for_live(request):
            reasons.append("inventory cannot support the requested quantity by the deadline")
        if request["baseline_transaction_total"] > request["buyer_budget_ceiling"] + 1e-9:
            reasons.append("the requested transaction exceeds the buyer's budget ceiling")
        reason_text = " and ".join(reasons) if reasons else "no candidate satisfies the locked constraints and risk gate"
        why = [
            f"No safe transaction satisfies the request because {reason_text}.",
            f"{len(result['candidates'])} alternatives were checked and {len(survivors)} survived the P05 gate.",
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
            "available": request["availability"]["available"],
            "incoming_available": request["availability"]["incoming_available"],
            "incoming_quantity": request["availability"]["incoming_available"],
            "baseline_transaction_total": request["baseline_transaction_total"],
            "buyer_budget_ceiling": request["buyer_budget_ceiling"],
        },
        "decision": result["decision"],
        "baseline": result.get("reference"),
        "candidate_count": len(result.get("candidates", [])),
        "risk_gate_rejections": result.get("risk_gate_rejections", 0),
        "survivor_count": len(survivors),
        "selected": selected,
        "top_safe_alternatives": alternatives,
        "why": why,
        "execution": {"available": False, "reason": "Live decisions are not persisted payment orders."},
    }


def inventory_feasible_for_live(request: dict) -> bool:
    """Recompute the live inventory constraint from the locked merchant state."""
    data = load_locked_data()
    state = data["merchant_states_by_sku"][request["target_sku_id"]]
    return request["requested_quantity"] <= available_for_window(state, request["deadline_days"])["available"]


@APP.get("/ai/risk/health")
def risk_health():
    """Small readiness check that also verifies the model can be loaded."""
    model = get_risk_model()
    return {"status": "ok", "model_version": model.version}


app = APP

"""AI-facing and live-decision ASGI entrypoint for MIRROR.

The original ``backend.main:app`` remains the deterministic decision engine.
This entrypoint adds the interactive live-decision surface and applies the
learned SLA-risk model as a second safety gate after deterministic P05 filtering.

Architecture:
    1. MIRROR generates/evaluates candidates with Monte Carlo + P05.
    2. P05 removes candidates with unacceptable downside risk.
    3. ML scores the remaining live candidates for SLA-miss risk.
    4. A candidate must pass BOTH gates to be eligible for a live recommendation.
    5. The deterministic engine remains the source of economic/constraint logic;
       ML is a safety veto, not an autonomous transaction generator.

The persisted 500-request experiment remains untouched.
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
    score_candidate,
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


def _ml_score_candidate(candidate: dict, model) -> dict:
    """Run the learned SLA-risk model on the exact live candidate."""
    data = load_locked_data()
    state = data["merchant_states_by_sku"][candidate["sku_id"]]
    features = risk_features_for_request(
        state,
        candidate["quantity"],
        candidate["delivery_window_days"],
    )
    probability = model.predict_probability(features)
    return {
        **candidate,
        "ml_sla_miss_probability": round(probability, 6),
        "ml_risk_level": "HIGH" if probability >= model.threshold else "LOW",
        "ml_passes_safety_gate": probability < model.threshold,
        "ml_top_feature_contributions": model.explain(features),
        "ml_model_version": model.version,
        "ml_threshold": model.threshold,
    }


def _apply_live_ml_gate(result: dict, request: dict) -> dict:
    """Apply ML as a second safety gate to the fresh live decision.

    P05 remains the first gate. ML is the second. The baseline is also scored
    when feasible, so the model can actually prevent acceptance of a high-risk
    baseline and force recovery through a safer candidate.
    """
    model = get_risk_model()
    p05_survivors = [
        candidate for candidate in result.get("candidates", [])
        if candidate.get("passes_risk_gate")
    ]

    baseline_ml = None
    if request["baseline_feasible"] and result.get("reference"):
        baseline_ml = _ml_score_candidate(result["reference"], model)

    ml_survivors = [_ml_score_candidate(candidate, model) for candidate in p05_survivors]
    ml_passers = [candidate for candidate in ml_survivors if candidate["ml_passes_safety_gate"]]
    ml_rejections = len(ml_survivors) - len(ml_passers)

    reference_score = result.get("reference_score", 0)
    improvement_threshold = reference_score + 0.05 * abs(reference_score)
    baseline_ml_pass = bool(baseline_ml and baseline_ml["ml_passes_safety_gate"])
    best = None
    decision = "REJECT"

    if request["baseline_feasible"] and baseline_ml_pass:
        competitive = [
            candidate for candidate in ml_passers
            if candidate.get("score", score_candidate(
                candidate["expected_net_contribution"],
                candidate["p05_net_contribution"],
                result.get("reference_p05", 0),
            )) > improvement_threshold
        ]
        if competitive:
            best = max(competitive, key=lambda candidate: candidate.get("score", float("-inf")))
            decision = "NEGOTIATE"
        else:
            decision = "ACCEPT"
            best = baseline_ml
    elif ml_passers:
        # Baseline is infeasible or ML-unsafe. A passing candidate is a genuine
        # recovery path even when it is not economically better than baseline.
        best = max(ml_passers, key=lambda candidate: candidate.get("score", float("-inf")))
        decision = "NEGOTIATE"

    by_identity = {
        (
            candidate["sku_id"], candidate["quantity"],
            candidate["delivery_window_days"], candidate["candidate_price"],
        ): candidate
        for candidate in ml_survivors
    }
    annotated_candidates = []
    for candidate in result.get("candidates", []):
        key = (
            candidate["sku_id"], candidate["quantity"],
            candidate["delivery_window_days"], candidate["candidate_price"],
        )
        annotated_candidates.append(by_identity.get(key, candidate))

    selected = baseline_ml if decision == "ACCEPT" else best
    result.update({
        "decision": decision,
        "best_candidate": best if decision == "NEGOTIATE" else None,
        "candidates": annotated_candidates,
        "ml": {
            "applied": True,
            "model_version": model.version,
            "threshold": model.threshold,
            "p05_survivor_count": len(p05_survivors),
            "ml_evaluated_count": len(ml_survivors),
            "ml_rejections": ml_rejections,
            "ml_pass_count": len(ml_passers),
            "baseline_evaluated": baseline_ml is not None,
            "baseline_passed": baseline_ml_pass if baseline_ml is not None else None,
            "baseline_probability": baseline_ml["ml_sla_miss_probability"] if baseline_ml else None,
            "selected_probability": selected["ml_sla_miss_probability"] if selected else None,
            "selected_passed": selected["ml_passes_safety_gate"] if selected else False,
        },
        "selected_with_ml": selected,
        "final_safe_count": len(ml_passers) + (1 if baseline_ml_pass else 0),
    })
    return result


def _competitive_alternatives(result: dict, request: dict) -> list[dict]:
    """Return only candidates that pass BOTH P05 and ML and are competitive."""
    survivors = [
        candidate for candidate in result.get("candidates", [])
        if candidate.get("passes_risk_gate") and candidate.get("ml_passes_safety_gate")
    ]
    if not survivors:
        return []

    if request["baseline_feasible"] and result.get("ml", {}).get("baseline_passed"):
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
    """Predict SLA-miss risk for a concrete live request."""
    data = load_locked_data()
    state = data["merchant_states_by_sku"].get(payload.sku_id)
    if state is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    model = get_risk_model()
    features = risk_features_for_request(state, payload.requested_quantity, payload.delivery_window_days)
    probability = model.predict_probability(features)
    return {
        "sku_id": payload.sku_id,
        "requested_quantity": payload.requested_quantity,
        "delivery_window_days": payload.delivery_window_days,
        "sla_miss_probability": round(probability, 6),
        "risk_level": "HIGH" if probability >= model.threshold else "LOW",
        "passes_safety_gate": probability < model.threshold,
        "threshold": model.threshold,
        "model_version": model.version,
        "top_feature_contributions": model.explain(features),
        "training_source": "locked synthetic MIRROR demand simulator",
        "evidence_status": "MODEL_OUTPUT_NOT_REAL_WORLD_PERFORMANCE",
    }


@APP.post("/ai/live-decision")
def live_decision(payload: LiveDecisionRequest):
    """Evaluate a fresh request through deterministic MIRROR + live ML safety."""
    request, experiment_seed = _live_request(payload)
    result = evaluate_request_decision(request, experiment_seed)
    result = _apply_live_ml_gate(result, request)

    selected = result.get("selected_with_ml")
    survivors = [
        candidate for candidate in result.get("candidates", [])
        if candidate.get("passes_risk_gate") and candidate.get("ml_passes_safety_gate")
    ]
    alternatives = _competitive_alternatives(result, request)

    if result["decision"] == "NEGOTIATE":
        if request["baseline_feasible"] and result["ml"].get("baseline_passed"):
            why = [
                "The requested transaction passed inventory, budget, P05 and ML SLA-risk checks, but a better safe option was found.",
                f"{len(result['candidates'])} alternatives were evaluated; {result['risk_gate_rejections']} failed P05, then {result['ml']['ml_rejections']} of the P05 survivors failed the ML safety gate.",
                f"The selected {selected['action_type'].lower()} option passed both safety gates and cleared the strict improvement threshold.",
            ]
        else:
            reasons = []
            if not inventory_feasible_for_live(request):
                reasons.append("available inventory is insufficient for the requested quantity by the deadline")
            if request["baseline_transaction_total"] > request["buyer_budget_ceiling"] + 1e-9:
                reasons.append("the requested transaction exceeds the buyer's budget ceiling")
            if result["ml"].get("baseline_passed") is False:
                reasons.append("the baseline was flagged by the ML SLA-risk model")
            reason_text = " and ".join(reasons) if reasons else "the original constraints could not be met"
            why = [
                f"The original request is not directly safe because {reason_text}.",
                f"{len(result['candidates'])} alternatives were evaluated; {result['risk_gate_rejections']} failed P05 and {result['ml']['ml_rejections']} additional P05 survivors failed the ML safety gate.",
                f"MIRROR selects the highest-scoring candidate that passed both safety gates: {selected['action_type'].lower()}.",
            ]
    elif result["decision"] == "ACCEPT":
        why = [
            "The requested transaction is feasible and passed both MIRROR's deterministic P05 gate and the ML SLA-risk safety gate.",
            f"{len(result['candidates'])} alternatives were checked; {result['risk_gate_rejections']} failed P05 and {result['ml']['ml_rejections']} P05 survivors failed ML, leaving no safer option that clears the strict improvement threshold.",
            "MIRROR therefore keeps the original request.",
        ]
    else:
        reasons = []
        if not inventory_feasible_for_live(request):
            reasons.append("inventory cannot support the requested quantity by the deadline")
        if request["baseline_transaction_total"] > request["buyer_budget_ceiling"] + 1e-9:
            reasons.append("the requested transaction exceeds the buyer's budget ceiling")
        if result["ml"].get("baseline_passed") is False:
            reasons.append("the baseline failed the ML SLA-risk safety gate")
        reason_text = " and ".join(reasons) if reasons else "no candidate satisfies both safety gates and the locked constraints"
        why = [
            f"No safe transaction satisfies the request because {reason_text}.",
            f"{len(result['candidates'])} alternatives were checked; {result['risk_gate_rejections']} failed P05 and {result['ml']['ml_rejections']} failed the ML safety gate.",
            "MIRROR recommends no safe deal instead of inventing a transaction.",
        ]

    return {
        "mode": "LIVE_REQUEST",
        "evidence_status": "FRESH_DETERMINISTIC_EVALUATION_WITH_LIVE_ML_SAFETY_GATE",
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
        "baseline_ml": result.get("ml", {}).get("baseline_probability"),
        "candidate_count": len(result.get("candidates", [])),
        "p05_gate_rejections": result.get("risk_gate_rejections", 0),
        "ml_gate_rejections": result.get("ml", {}).get("ml_rejections", 0),
        "survivor_count": len(survivors),
        "selected": selected,
        "top_safe_alternatives": alternatives,
        "why": why,
        "ml": result.get("ml"),
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

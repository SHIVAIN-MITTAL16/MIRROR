"""AI-facing ASGI entrypoint for MIRROR.

The original ``backend.main:app`` remains untouched while this entrypoint exposes
new AI routes on the same FastAPI application. Keeping the integration point
separate lets us benchmark the learned layer without destabilising the existing
merchant dashboard.

Run locally with:
    uvicorn backend.ai_app:app --host 0.0.0.0 --port 8002
"""

from fastapi import HTTPException
from pydantic import BaseModel, Field

from backend.main import APP, load_locked_data
from backend.risk_model import get_risk_model, risk_features_for_request


class RiskPredictionRequest(BaseModel):
    sku_id: str = Field(min_length=1)
    requested_quantity: int = Field(gt=0)
    delivery_window_days: int = Field(ge=0, le=30)


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


@APP.get("/ai/risk/health")
def risk_health():
    """Small readiness check that also verifies the model can be loaded."""
    model = get_risk_model()
    return {"status": "ok", "model_version": model.version}


app = APP

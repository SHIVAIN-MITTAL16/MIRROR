# MIRROR AI Risk Model

## Status

**Implemented in code; benchmark execution is the next verification step.**

The model is exposed through `backend/ai_app.py` and implemented in `backend/risk_model.py`.

## What the model predicts

The first learned model predicts:

> **P(SLA miss | merchant state, requested quantity, delivery window)**

This is deliberately narrower than the final MIRROR intelligence layer. A narrow, measurable model is more defensible than claiming a vague "AI risk score".

## Training source

The current corpus is generated from the locked MIRROR demand/inventory simulator. Each row represents one possible fulfilment path. The label is `1` when simulated available inventory after demand cannot satisfy the requested quantity.

This distinction is important:

- **Real ML:** yes — a learned logistic model is fitted from generated examples.
- **Real-world performance:** not claimed — the corpus is synthetic.
- **Competition evidence:** must report the synthetic nature of the benchmark honestly.

The next data milestone is a stronger held-out corpus and, if available, real/competition-provided data.

## Feature contract

```text
requested_quantity
delivery_window_days
net_inventory
incoming_quantity
incoming_due
demand_mean
demand_shape
quantity_to_inventory
quantity_to_expected_demand
inventory_cover_days
```

The features are intentionally operational rather than textual. The model should be able to explain why a transaction is risky using merchant-state facts.

## Model

Current baseline: **regularized logistic regression** implemented with NumPy.

Why start here:

1. It is small enough to audit line-by-line.
2. It has deterministic training.
3. Feature scaling is explicit.
4. Coefficients are inspectable.
5. It avoids introducing a heavy dependency before the benchmark proves that a more complex model is justified.

## Evaluation split

The test set is **SKU-held-out**, not a random row split.

This prevents nearly identical paths from the same SKU appearing in both training and testing. The first 40 locked SKUs are used for training and the remaining 10 are held out for evaluation.

Metrics exposed by the API:

- accuracy
- precision
- recall
- F1
- ROC-AUC
- positive rate
- confusion-matrix counts

The model uses a conservative `0.35` probability threshold because missing a genuine SLA risk is more harmful to a recovery system than escalating a safe request for further analysis. The threshold is a policy choice, not a claim that `0.35` is universally optimal.

## Runtime API

Use the AI entrypoint:

```powershell
uvicorn backend.ai_app:app --host 0.0.0.0 --port 8002
```

Endpoints:

```text
GET  /ai/risk/health
GET  /ai/risk/model
POST /ai/risk/predict
```

Example request:

```json
{
  "sku_id": "LAP-007",
  "requested_quantity": 17,
  "delivery_window_days": 5
}
```

The prediction response includes the model version, probability, threshold, evidence status and top feature contributions.

## Safety boundary

The risk model does **not** approve payments and does **not** mutate inventory. It is a prediction service only.

The deterministic MIRROR decision engine, future Policy Engine and future Execution Governor remain responsible for deciding whether an action is allowed.

That separation is intentional:

```text
ML prediction
      ↓
Candidate reasoning
      ↓
Simulation / P05
      ↓
Policy
      ↓
Execution
```

An inaccurate prediction can therefore be detected and overridden by downstream safety controls rather than directly moving money.

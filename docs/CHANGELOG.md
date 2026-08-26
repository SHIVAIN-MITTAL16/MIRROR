# MIRROR Changelog

## 2026-08-26

### Demo evidence integration

- Added a clearly labelled experimental ML SLA-risk evidence section to the dashboard.
- Added a persisted frontend evidence snapshot sourced from the completed risk-model benchmarks rather than invented UI values.
- Added two replayable demo cases: a risk-caught negotiation and a safer-alternative substitution-to-price case.
- Added held-out precision/recall/F1, calibration, risk-separation and end-to-end impact figures to the demo surface.
- Added explicit honesty guardrails in the UI: synthetic evaluation, experimental threshold, and no claim of profit improvement.
- Added responsive styling for the new evidence surface without changing the deterministic decision engine.

## 2026-08-25

### Real AI foundation

- Added `backend/risk_model.py` with a deterministic, regularized logistic-regression SLA-risk model.
- Training corpus is generated from the locked demand simulator and is explicitly labelled synthetic.
- Evaluation uses a SKU-held-out split to avoid row-level leakage.
- Added model provenance, threshold, feature contract and held-out metrics metadata.
- Added feature-level contribution output for auditability.
- Added `backend/ai_app.py` as a separate AI-facing ASGI entrypoint so the existing dashboard remains stable while the learned layer is benchmarked.
- Added `/ai/risk/health`, `/ai/risk/model`, and `/ai/risk/predict`.
- Added `backend/test_risk_model.py` for deterministic training, metric bounds, prediction bounds and input validation.
- Added `docs/AI_RISK_MODEL.md` and `docs/CURRENT_STATE.md` to keep implementation claims synchronized with code.

### Engineering rule introduced

Do not call the model "production-grade" or "real-world validated" until the held-out benchmark and scenario-cost analysis have been executed and recorded.

# MIRROR — Current State Ledger

**Last updated:** 25 August 2026  
**Branch:** `mirror-visual-redesign`

This file is intentionally blunt. It records what is implemented, what is only designed, and what still needs evidence.

## Implemented and evidenced in the repository

- Locked 50-SKU demand/inventory dataset with validation.
- Persisted five-seed experiment artifacts.
- Monte Carlo candidate evaluation using 10,000 paths.
- Empirical demand CDFs and P05 downside metric.
- Candidate search across price, quantity, timing and substitution.
- ACCEPT / NEGOTIATE / REJECT decision states.
- Persisted request explorer and dashboard APIs.
- Razorpay test-mode order/payment boundary.
- Server-side payment signature verification.
- Responsive/cinematic frontend and decision visualization.
- First learned SLA-risk model implemented in `backend/risk_model.py`.
- AI-facing risk API implemented in `backend/ai_app.py`.
- Risk-model unit tests added in `backend/test_risk_model.py`.

## Implemented but benchmark evidence still pending

- SKU-held-out ML evaluation metrics need to be executed and recorded.
- Runtime AI endpoints need deployment validation.
- Model threshold needs scenario-level cost analysis.

## Designed, not yet implemented

- Decision Contract.
- Tool-using LLM agent.
- Adversarial/red-team agent.
- Failure-cascade graph runtime.
- Policy Engine.
- Execution Governor.
- Immutable agent audit trace.
- Failure-injection laboratory.
- Counterfactual explorer.
- Recovery benchmark with measured money recovered.
- Shadow mode.
- Drift detection.

## Truth policy

A feature is **DONE** only when:

1. code exists;
2. tests or reproducible evidence exist;
3. the feature can be demonstrated;
4. documentation matches the implementation.

Until then it stays explicitly marked as pending.

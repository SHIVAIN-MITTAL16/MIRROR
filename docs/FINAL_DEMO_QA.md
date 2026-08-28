# MIRROR — Final Demo QA Checkpoint

**Date:** 28 August 2026  
**Branch:** `mirror-visual-redesign`

## What was audited

- Deterministic MIRROR decision flow: buyer request → baseline → candidate generation → Monte Carlo → P05 gate → selected decision.
- Persisted five-seed experiment artifacts and dashboard metrics.
- ML SLA-risk evidence boundary and demo cases.
- Selected transaction, constraint recovery, risk protection, negotiation levers and request explorer sections.
- New **Live Decision Room** for fresh, non-persisted buyer requests.
- Razorpay execution boundary and its test-mode safety behavior.
- Frontend wording against the persisted experiment evidence.

## Corrections made

### 1. Dashboard metric semantics

The former **Value Created** heading was too vague for a judge. It is now **Performance vs Baseline**, with the primary figure explicitly described as **Mean uplift across five seeds**.

### 2. P05 section semantics

The former generic **Risk Protection** wording is now **P05 Risk Protection**. The copy distinguishes the 3,698 alternative candidates, 2,477 P05 rejections and 1,221 survivors.

### 3. Selected P05 semantics

For a NEGOTIATE decision the dashboard shows the selected candidate's P05 and expected contribution. For ACCEPT it identifies the baseline P05. For REJECT it shows **NO-DEAL P05** instead of pretending that a transaction was selected.

### 4. ML demo honesty

The safer-alternative ML case shows both the old and new expected contribution. The persisted evidence shows that the experimental ML layer currently trades expected contribution for additional safety filtering.

### 5. Hero decision label

The hero no longer prints an empty action label when the selected result has no candidate action type.

### 6. Live Decision Room

A fresh request can now be entered through the UI and evaluated by the **same deterministic MIRROR engine** used by the persisted experiment. The live path performs candidate generation, Monte Carlo evaluation, P05 filtering and final selection, then returns the decision and a field-backed explanation.

The live request is deliberately **not added to the 500 persisted experiment rows**. It is an interactive product surface, not a new benchmark claim.

## Locked evidence used for the demo

- 500 persisted requests across five deterministic seeds.
- 4,108 total candidates evaluated in the locked experiment.
- 3,698 negotiation candidates enter the P05 risk-gate aggregate shown in the dashboard.
- 2,477 negotiation candidates fail the P05 gate; 1,221 survive.
- 55 NEGOTIATE decisions, 390 ACCEPT decisions and 55 REJECT decisions.
- 35 of 45 constraint-conflict requests are rescued: 77.78%.
- ML experiment: 2/500 decisions changed; expected contribution changed by -0.84%; P05 changed by -0.59%.

## Important limitations before recording

1. The experiment data is synthetic and locked; it is not real merchant production traffic.
2. The ML panel is persisted experiment evidence. It must not be described as production-validated ML performance.
3. The deterministic P05 engine remains the transaction-selection authority.
4. The ML experiment currently does **not** demonstrate a profit increase.
5. The Live Decision Room evaluates against the locked merchant/catalog state but does **not** persist the request as benchmark evidence or create a live payment order.
6. The live route is exposed by `backend.ai_app:app`; the deployed Render service must use that ASGI app for the new endpoint to exist.

## Recording gate

**Do not record the final demo until the deployed browser is checked once after the latest commits are deployed.**

Minimum browser smoke test:

1. Open the deployed dashboard.
2. Skip/replay the cinematic intro once.
3. Confirm the **Live Decision Room** appears near the top.
4. Submit a fresh request and confirm it returns ACCEPT, NEGOTIATE or REJECT with candidate count, safe survivors, P05 rejections and a field-backed explanation.
5. Change quantity/budget/deadline and run it again; confirm the response changes when the request changes.
6. Click **Analyze a request** for the persisted demo flow.
7. Confirm the selected request, decision pipeline and explanation all load.
8. Confirm the ML panel appears and both demo-case replay buttons work.
9. Confirm sections 04–10 render without layout or console errors.
10. Load at least one ACCEPT, one NEGOTIATE and one REJECT request from the explorer.
11. Confirm REJECT shows **NO SAFE DEAL** rather than a fake selected transaction.
12. Confirm the Razorpay boundary does not claim a payment succeeded unless test credentials and a real test checkout are actually configured.
13. Record the demo only after this smoke test passes.

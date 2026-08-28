# MIRROR — Final Demo QA Checkpoint

**Date:** 28 August 2026  
**Branch:** `mirror-visual-redesign`

## What was audited

- Deterministic MIRROR decision flow: buyer request → baseline → candidate generation → Monte Carlo → P05 gate → selected decision.
- Persisted five-seed experiment artifacts and dashboard metrics.
- ML SLA-risk evidence boundary and demo cases.
- Selected transaction, constraint recovery, risk protection, negotiation levers and request explorer sections.
- Razorpay execution boundary and its test-mode safety behavior.
- Frontend wording against the persisted experiment evidence.

## Corrections made

### 1. Dashboard metric semantics

The former **Value Created** heading was too vague for a judge. It is now **Performance vs Baseline**, with the primary figure explicitly described as **Mean uplift across five seeds**.

### 2. P05 section semantics

The former generic **Risk Protection** wording is now **P05 Risk Protection**. The candidate flow now explicitly says:

`ALTERNATIVES → P05 GATE → SAFE SURVIVORS → SELECTED`

The copy distinguishes the 3,698 alternative candidates, 2,477 P05 rejections and 1,221 survivors.

### 3. Selected P05 semantics

For a NEGOTIATE decision the dashboard shows the selected candidate's P05 and expected contribution. For ACCEPT it identifies the baseline P05. For REJECT it shows **NO-DEAL P05** instead of pretending that a transaction was selected.

### 4. ML demo honesty

The safer-alternative ML case now shows both the old and new expected contribution. This prevents the UI from implying that the safer alternative improved every metric. The persisted evidence shows that the experimental ML layer currently trades expected contribution for additional safety filtering.

### 5. Hero decision label

The hero no longer prints an empty action label when the selected result has no candidate action type.

## Locked evidence used for the demo

- 500 persisted requests across five deterministic seeds.
- 4,108 total candidates evaluated in the locked experiment.
- 3,698 negotiation candidates enter the P05 risk-gate aggregate shown in the dashboard.
- 2,477 negotiation candidates fail the P05 gate; 1,221 survive.
- 55 NEGOTIATE decisions, 390 ACCEPT decisions and 55 REJECT decisions.
- 35 of 45 constraint-conflict requests are rescued: 77.78%.
- Five-seed mean uplift is presented as uplift versus the persisted baseline reference, not as guaranteed profit.
- ML experiment: 2/500 decisions changed; expected contribution changed by -0.84%; P05 changed by -0.59%.

## Important limitations before recording

1. The experiment data is synthetic and locked; it is not real merchant production traffic.
2. The ML panel is persisted experiment evidence. It must not be described as production-validated ML performance.
3. The deterministic P05 engine remains the transaction-selection authority.
4. The ML experiment currently does **not** demonstrate a profit increase.
5. GitHub Actions has a backend-test workflow configured, but no successful remote CI run is independently evidenced at this checkpoint.
6. Final browser/deployment validation still needs to be performed on the actual deployed URL after the latest branch commits are deployed.

## Recording gate

**Do not record the final demo until the deployed browser is checked once after the latest commits.**

Minimum browser smoke test:

1. Open the deployed dashboard.
2. Skip/replay the cinematic intro once.
3. Click **Analyze a request**.
4. Confirm the selected request, decision pipeline and explanation all load.
5. Confirm the ML panel appears as section 03 and both demo-case replay buttons work.
6. Confirm sections 04–10 render without layout or console errors.
7. Load at least one ACCEPT, one NEGOTIATE and one REJECT request from the explorer.
8. Confirm REJECT shows **NO SAFE DEAL** rather than a fake selected transaction.
9. Confirm the Razorpay boundary does not claim a payment succeeded unless test credentials and a real test checkout are actually configured.
10. Record the demo only after this smoke test passes.

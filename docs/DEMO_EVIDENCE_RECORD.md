# MIRROR / Grid Sentinel AI — Demo Evidence Record

## 2026-08-26 checkpoint

This document records the evidence currently safe to present in the final demo. It deliberately separates validated results from experimental results and unresolved work.

## 1. Locked experiment

- Five deterministic seeds: `20260821`–`20260825`.
- 500 requests total.
- 4,108 candidates evaluated.
- 10,000 Monte Carlo paths per candidate.
- Baseline decisions: ACCEPT 390 (78%), NEGOTIATE 55 (11%), REJECT 55 (11%).
- Constraint conflicts: 45; rescued: 35/45 = 77.78%.
- P05 risk-gate rejections: 2,477.
- Total runtime across five seeds: about 220 seconds.
- Selected expected net contribution: ₹68,274,540.62.
- Selected P05 contribution: ₹62,993,644.20.

## 2. ML SLA-risk experiment

Model: `sla-logreg-v1-seed-20260825`

Experimental threshold: `0.35`.

On P05-approved validation scenarios:

- ML PASS: 478 scenarios; mean observed SLA miss 3.95%; 11.92% >=10%; 8.16% >=20%; 5.65% >=30%; maximum 45.17%.
- ML FAIL: 11 scenarios; mean observed SLA miss 32.32%; 90.91% >=10%; 90.91% >=20%; 72.73% >=30%; maximum 43.80%.
- FAIL/PASS mean-risk separation: 8.19x.

Threshold sweep shows the expected safety/coverage tradeoff. Threshold 0.35 is retained only for the experimental end-to-end comparison; it is not claimed to be production-optimal.

## 3. ML end-to-end comparison

Existing MIRROR gate:

- ACCEPT 390
- NEGOTIATE 55
- REJECT 55
- Selected requests: 445
- Expected contribution: ₹68,274,540.62
- P05: ₹62,993,644.20

Experimental P05 + ML gate:

- ACCEPT 391
- NEGOTIATE 53
- REJECT 56
- Selected requests: 444
- Expected contribution: ₹67,702,153.67
- P05: ₹62,623,454.20

Impact:

- 2/500 decisions changed = 0.4%.
- Expected contribution changed by -₹572,386.94 = -0.84%.
- P05 changed by -₹370,190 = -0.59%.
- 36 additional ML rejections among 1,221 P05 survivors = 2.95%.

Interpretation: ML currently behaves as a small additional safety filter. The locked experiment does **not** demonstrate a profit increase. This negative result is part of the demo evidence, not something to hide.

## 4. Strong ML demo cases

### Risk caught

Seed `20260821`, request `22`:

- Existing decision: NEGOTIATE.
- Expected net: ₹145,168.07.
- P05: ₹110,550.
- Observed SLA miss: 32.78%.
- ML predicted SLA-miss risk: 48.59%.
- Experimental ML result: REJECT.

### Riskier option replaced

Seed `20260825`, request `4`:

- Existing selected substitution: expected net ₹591,787.95; P05 ₹497,904; observed SLA miss 38.39%.
- ML rejected that candidate and selected a PRICE alternative.
- New expected net: ₹531,360.40.
- New P05: ₹525,463.
- New predicted SLA-miss risk: 16.36%.
- New observed SLA miss: 0.51%.

This case is useful because the ML layer sacrifices expected contribution while materially improving the observed SLA outcome in the persisted benchmark case.

## 5. Existing MIRROR value already demonstrated

- Deterministic seeded reproducibility.
- Monte Carlo uncertainty evaluation.
- P05 downside-risk gate.
- Constraint-conflict rescue.
- Negotiation levers: substitution, quantity and timing.
- Explainable request/candidate/decision pipeline.
- Persisted 500-request explorer.
- Truthful Razorpay execution boundary.

## 6. Validation / QA checkpoint

A local backend test run recorded in the project evidence executed 12 tests successfully in 1.787 seconds with status `OK`.

The risk-model test suite covers deterministic training, non-empty held-out evaluation, bounded/explainable prediction, and invalid feature rejection.

The GitHub workflow is configured to install dependencies and run backend unit tests on the `mirror-visual-redesign` branch. A successful remote CI run has **not** been independently evidenced at this checkpoint, so the demo must not claim CI passed.

## 7. Known failures and limitations

- Current ML gate reduces expected contribution by about 0.84% in the locked end-to-end experiment.
- ML PASS is not guaranteed safe; some P05-approved candidates still have high observed SLA miss.
- Data is synthetic/locked and does not establish production performance.
- Some request-level fields were not persisted in the raw experiment artifacts.
- No production-optimal ML threshold has been established.
- No guaranteed SLA-improvement claim is justified.
- The broader AI-agent, adversarial/failure-injection, execution-governor, audit-trace, counterfactual, recovery-benchmark, shadow-mode and drift-detection roadmap is not yet complete.
- Live browser/deployment verification remains a final QA step.

## 8. Final demo truth statement

> MIRROR is a risk-aware commerce decision engine that evaluates a buyer transaction under uncertainty, searches alternatives, filters them through downside risk, and selects a transaction that can survive the constraints. We then tested whether an ML SLA-risk layer could add another safety signal without replacing the deterministic engine. It strongly separates higher-risk candidates in the locked experiment, but currently trades about 0.84% expected contribution for that additional filtering. We show both the successes and the failures so the system is evaluated on evidence rather than a manufactured success story.

## 9. Demo sequence to preserve

`REQUEST → CONSTRAINT CHECK → CANDIDATE GENERATION → MONTE CARLO → P05 GATE → ML SLA GATE (experimental) → ACCEPT / NEGOTIATE / REJECT → WHY → SAFE ALTERNATIVE / SELECTED ACTION → EXECUTION BOUNDARY`

The demo should explicitly show:

1. One successful baseline decision.
2. One constraint-conflict rescue.
3. One P05 rejection.
4. One ML risk-caught case.
5. One ML safer-alternative case.
6. The aggregate 500-request evidence.
7. Five-seed stability.
8. The ML tradeoff and negative contribution result.
9. The Razorpay boundary without fake payment success.
10. Limitations and remaining roadmap.

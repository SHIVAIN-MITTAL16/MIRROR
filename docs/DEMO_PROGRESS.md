# MIRROR Demo Progress Ledger

## 2026-08-26 — ML evidence integration

### Step completed
Integrated the completed SLA-risk benchmark into the existing MIRROR visual system without modifying the deterministic decision engine, persisted seed artifacts, or Razorpay flow.

### Repository changes
- `frontened/ml-risk.js` — experimental ML evidence section and replay controls.
- `frontened/ml-risk.css` — responsive presentation styling.
- `frontened/assets/ml-risk-evidence.json` — persisted benchmark evidence snapshot.
- `frontened/index.html` — mounted the new section and renumbered the 10 numbered dashboard sections.
- `docs/CHANGELOG.md` — recorded the integration.
- `docs/CURRENT_STATE.md` — synchronized implementation status and remaining validation.

### Evidence displayed
- Model: `sla-logreg-v1-seed-20260825`.
- Threshold: `0.35`.
- SKU-held-out synthetic evaluation: 80,000 train rows / 20,000 test rows.
- Threshold-0.35 precision: 65.64%.
- Recall: 99.90%.
- F1: 79.23%.
- Brier score: 0.052.
- Expected calibration error: 12.66%.
- P05-approved mean-risk separation: 8.19×.
- End-to-end decision change: 2 / 500 = 0.4%.
- Experimental expected-contribution change: -0.84%.
- Experimental P05 change: -0.59%.

### Demo cases
1. Seed `20260821`, request `22`: baseline `NEGOTIATE`; experimental ML `REJECT`; observed SLA miss 32.78%; predicted risk 48.59%.
2. Seed `20260825`, request `4`: old `SUBSTITUTION`; safer `PRICE` alternative; old observed SLA miss 38.39%; new predicted risk 16.36%; new observed SLA miss 0.51%.

### Explicit non-claims
- ML is not production validated.
- The benchmark uses synthetic MIRROR scenarios.
- The current experiment does not demonstrate a profit increase.
- Threshold 0.35 is not claimed to be production-optimal.
- The ML panel is evidence presentation, not a replacement for the deterministic P05 decision engine.

## Remaining validation gate
- Browser inspection at 1440×900.
- Browser inspection at 1280×720.
- Browser inspection at 768×720.
- Browser inspection at 390×844.
- Confirm no horizontal overflow.
- Confirm all 10 numbered sections render.
- Confirm ML replay buttons load the real persisted requests.
- Confirm explorer filters and selected-row state still work.
- Confirm ACCEPT / NEGOTIATE / REJECT real requests.
- Confirm zero console errors.
- Confirm zero failed API requests attributable to the redesign.
- Confirm Razorpay remains truthful/test-mode or disabled.

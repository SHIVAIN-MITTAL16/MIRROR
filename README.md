# MIRROR

### Merchant AI Commerce Intelligence

> **Find the transaction that survives the risk.**

MIRROR is a deterministic commerce decision engine for transactions under uncertainty. It evaluates whether a buyer request should be **accepted, recovered through negotiation, or safely declined** while protecting downside risk.

**Live demo:** https://mirror-rdqq.onrender.com/

## Core idea

For a request, MIRROR follows:

```text
BUYER REQUEST
      ↓
BASELINE CHECK
      ↓
CANDIDATE GENERATION
      ↓
MONTE CARLO
      ↓
P05 DOWNSIDE-RISK GATE
      ↓
SAFE SURVIVORS
      ↓
ACCEPT / NEGOTIATE / REJECT
      ↓
PAYMENT BOUNDARY
```

The deterministic P05 engine remains the transaction-selection authority. The ML layer is an experimental second safety signal, not the final decision maker.

## Live Decision Room

The dashboard now includes a **Live Decision Room** so a judge can enter a fresh demand instead of only replaying persisted examples.

The user enters:

- product / SKU
- quantity
- budget
- deadline
- price flexibility
- quantity flexibility
- timing flexibility
- substitution tolerance

MIRROR then runs the **actual existing decision engine**: baseline evaluation, candidate generation, Monte Carlo evaluation, P05 filtering and final selection. The UI returns:

- ACCEPT / NEGOTIATE / REJECT
- candidates evaluated
- P05 rejections
- safe survivors
- selected transaction, when one exists
- top safe alternatives
- a field-backed explanation of why the decision won

This is deliberately **not an LLM chatbot**. The live request is not appended to the 500-request benchmark and is not presented as production traffic. It evaluates against the locked merchant/catalog state.

Implementation details are documented in `docs/LIVE_DECISION_ROOM.md`.

## Decision states

| Decision | Meaning |
| --- | --- |
| **ACCEPT** | The baseline remains the safest selected transaction. |
| **NEGOTIATE** | A risk-gate-passing alternative beats the baseline under the decision rule. |
| **REJECT** | No candidate satisfies the persisted decision rule; MIRROR recommends no safe deal. |

## Locked experiment evidence

The dashboard is backed by deterministic persisted experiment records rather than live/randomly changing benchmark numbers.

- **500** persisted buyer requests across five deterministic seeds
- **4,108** total candidates evaluated
- **3,698** negotiation/alternative candidates enter the P05 aggregate
- **2,477** fail the P05 risk gate
- **1,221** survive the P05 gate
- **390 ACCEPT**, **55 NEGOTIATE**, **55 REJECT**
- **35 / 45** constraint-conflict requests rescued (**77.78%**)

The five-seed headline is **mean uplift versus the persisted baseline reference**. It is not guaranteed profit or production ROI.

## Dashboard evidence

### Persisted request + decision pipeline

The dashboard shows the persisted buyer request, baseline, candidate evaluation, constraint check, P05 gate, survivors and selected decision.

### Experimental ML safety gate

Persisted ML evidence:

- model: `sla-logreg-v1-seed-20260825`
- 20,000 held-out synthetic rows
- precision: **65.64%**
- recall: **99.90%**
- F1: **79.23%**
- end-to-end impact: **2 / 500 decisions changed (0.4%)**
- expected contribution change: **-0.84%**
- P05 change: **-0.59%**

The ML experiment therefore does **not** claim a profit increase. Its demonstrated role is additional SLA-risk filtering evidence.

### ML demo cases

1. **Risk caught:** an existing NEGOTIATE decision is rejected by the experimental ML safety check when predicted SLA-miss risk is high.
2. **Safer alternative:** an existing substitution is replaced by a price alternative after the ML check. Both old and new expected contribution are shown because the safer outcome can trade value for safety.

### Performance vs Baseline

Reports mean uplift across the five deterministic seeds and explicitly avoids presenting it as guaranteed profit.

### Constraint Recovery

Locked evidence: **35 recovered out of 45 constraint-conflict requests = 77.78% rescue rate.**

### P05 Risk Protection

The aggregate story is:

```text
ALTERNATIVES → P05 GATE → SAFE SURVIVORS → SELECTED
```

The dashboard shows **2,477 P05 failures** and **1,221 survivors** among the 3,698 negotiation candidates in the aggregate.

### Negotiation Levers

Selected-lever evidence:

- Substitution: **39 (70.9%)**
- Quantity: **15 (27.3%)**
- Timing: **1 (1.8%)**
- Price: **0 (0.0%)**

This is descriptive of the persisted evidence set, not a universal rule.

### Request Explorer

The persisted request ledger lets a judge inspect individual **ACCEPT, NEGOTIATE and REJECT** cases instead of seeing only aggregate metrics.

### Execution Boundary

Razorpay is deliberately separated from the decision engine. MIRROR can recommend a transaction without pretending that payment happened. Test credentials are required for checkout and payment signatures are verified server-side.

## Architecture

```text
                         BUYER REQUEST
                              │
                              ▼
                     DETERMINISTIC ENGINE
                              │
                ┌─────────────┴─────────────┐
                │                           │
          candidate search            constraint check
                │                           │
                └─────────────┬─────────────┘
                              ▼
                         MONTE CARLO
                              ▼
                           P05 GATE
                              ▼
                       SAFE SURVIVORS
                              ▼
                    FINAL DECISION AUTHORITY
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
            ACCEPT        NEGOTIATE        REJECT
                              │
                              ▼
                       PAYMENT BOUNDARY

             EXPERIMENTAL ML SAFETY SIGNAL
                       ───────────────►
                 evidence / extra filter
                 NOT the final authority
```

The live API is exposed by `backend.ai_app:app`. It imports the existing deterministic application and adds `/ai/live-decision`; it does not replace the decision engine.

## Project structure

```text
MIRROR/
├── backend/
│   ├── main.py
│   ├── ai_app.py
│   ├── risk_model.py
│   ├── test_dashboard.py
│   ├── test_decision_engine.py
│   ├── test_risk_model.py
│   └── test_live_decision.py
├── data/
├── experiments/
├── frontened/
│   ├── index.html
│   ├── app.js
│   ├── app.css
│   ├── live-room.css
│   ├── tokens.css
│   ├── intelligence-core.js
│   ├── decision-pipeline.js
│   └── assets/
├── docs/
│   ├── FINAL_DEMO_QA.md
│   └── LIVE_DECISION_ROOM.md
├── render.yaml
└── README.md
```

## Run locally

### Existing dashboard

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For the full dashboard, use the live ASGI entrypoint so the Live Decision Room is registered too:

```powershell
uvicorn backend.ai_app:app --host 0.0.0.0 --port 8002
```

Then open:

```text
http://127.0.0.1:8002/
```

The backend also exposes `/health`.

## Render deployment

Render must start the **AI/live entrypoint**, not only `backend.main:app`:

```text
uvicorn backend.ai_app:app --host 0.0.0.0 --port $PORT
```

The repository includes `render.yaml` with this configuration. For an existing Render service, change its Start Command in the service Settings and redeploy the branch. Render documents that an existing service's deploy commands can be modified from Settings.

## Payment configuration

Set Razorpay test credentials on the server when payment testing is required:

```text
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
```

Never commit credentials.

The Live Decision Room does **not** create a payment order. The persisted transaction flow remains the execution boundary.

## Validation

GitHub Actions runs the backend test suite on pushes to `mirror-visual-redesign`. The live-decision implementation passed the latest remote backend test job before the final documentation commit.

The final deployed-browser smoke test is still required before recording. See `docs/FINAL_DEMO_QA.md`.

## Important limitations

1. The experiment data is **synthetic and locked**; it is not real merchant production traffic.
2. The ML panel is **persisted experimental evidence**, not production-validated ML performance.
3. The deterministic P05 engine remains the **transaction-selection authority**.
4. The ML experiment currently does **not** demonstrate a profit increase.
5. Live Decision Room requests are fresh evaluations against the locked state, not new benchmark evidence.
6. Live Decision Room requests do not create live Razorpay payment orders.

## Status

**Active build — `mirror-visual-redesign`**

Current milestones:

- Persisted experiment-backed dashboard APIs
- Deterministic candidate evaluation and P05 downside gate
- Five-seed evidence-backed performance reporting
- Data-driven decision pipeline
- Constraint recovery analysis
- Negotiation-lever analysis
- Experimental ML SLA-risk safety layer
- ML persisted demo cases
- MIRROR vessel visual system
- Cinematic opening sequence
- Responsive dashboard refinement
- **Live Decision Room for fresh requests**
- Razorpay test-mode execution boundary
- Final demo QA checkpoint

## Repository

MIRROR on GitHub: https://github.com/SHIVAIN-MITTAL16/MIRROR

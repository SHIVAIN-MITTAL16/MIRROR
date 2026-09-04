# MIRROR

### Merchant AI Commerce Intelligence

> **Find the transaction that survives the risk.**

MIRROR is a **risk-aware commerce decision system** for transactions where price, inventory, quantity, delivery time, demand uncertainty, and service-level risk can change the outcome.

Instead of only asking *“Can we sell this?”*, MIRROR asks:

> **“Which transaction is still safe when uncertainty is taken seriously?”**

**Live Demo:** https://mirror-rrdq.onrender.com/

---

## What MIRROR does

A buyer provides:

- Product / SKU
- Quantity
- Budget
- Delivery deadline
- Price flexibility
- Quantity flexibility
- Timing flexibility
- Substitution tolerance

MIRROR then evaluates the request against the locked merchant/catalog state, generates recovery options, simulates uncertainty, filters downside risk, applies SLA-risk protection, and returns one of three outcomes:

**ACCEPT · NEGOTIATE · REJECT**

The live request is processed by the actual MIRROR decision pipeline. It is not an LLM chatbot and it is not a hard-coded demo response.

---

# The decision pipeline

```text
                    BUYER REQUEST
                         │
                         ▼
                BASELINE FEASIBILITY
                  inventory + budget
                         │
              ┌──────────┴──────────┐
              │                     │
           feasible          constraint conflict
              │                     │
              │               recovery levers
              │          price / quantity / timing /
              │                 substitution
              │                     │
              └──────────┬──────────┘
                         ▼
                CANDIDATE GENERATION
                         │
                         ▼
                  MONTE CARLO
                  EVALUATION
                         │
                         ▼
                     P05 GATE
                 downside protection
                         │
                         ▼
                  P05 SURVIVORS
                         │
                         ▼
                  ML SLA-RISK GATE
                  second safety layer
                         │
                         ▼
                  SAFE SURVIVORS
                         │
                         ▼
                FINAL DECISION LOGIC
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
           ACCEPT    NEGOTIATE    REJECT
                         │
                         ▼
                 PAYMENT BOUNDARY
```

## Why two safety gates?

The two gates solve different problems.

### P05 — economic downside protection

MIRROR uses Monte Carlo evaluation to model uncertain outcomes. The P05 gate filters candidates whose downside is unacceptable under the decision rule.

### ML — SLA-risk protection

The learned model predicts the probability of an SLA miss for the **exact live candidate**. A live candidate must pass the deterministic P05 gate **and** the ML safety gate to remain eligible.

The ML layer does **not** generate transactions and does not replace the deterministic engine. It is a **learned safety veto** that adds service-risk information to an otherwise deterministic decision process.

This makes the architecture explainable: economic and constraint logic remain deterministic, while ML contributes a separate risk signal.

---

# Live Decision Room

The Live Decision Room lets a judge create a fresh transaction and see the complete evaluation instead of replaying only fixed examples.

### Inputs

| Input | Purpose |
| --- | --- |
| SKU | Requested product |
| Quantity | Requested units |
| Budget | Buyer spending ceiling |
| Deadline | Required delivery window |
| Price flexibility | Allowed price movement |
| Quantity flexibility | Allowed quantity movement |
| Timing flexibility | Allowed delivery movement |
| Substitution | Whether alternative SKUs may be considered |

### Live output

MIRROR exposes the reasoning behind the result, including:

- Final decision
- Selected SKU and quantity
- Unit price / transaction economics
- Expected net contribution
- P05 downside value
- Candidates evaluated
- P05 rejections
- ML evaluations and ML rejections
- Safe survivors
- Competitive alternatives
- Decision explanation
- ML SLA-miss probability and threshold where applicable

Fresh requests are evaluated against the locked merchant/catalog state. They are **not appended to the persisted 500-request benchmark** and are not presented as production traffic.

---

# A critical design rule: more budget ≠ automatic substitution

MIRROR explicitly protects the buyer's requested product when the baseline is already feasible.

A huge budget should not cause the system to replace the requested SKU merely because another candidate happens to score slightly higher.

```text
Baseline feasible?
       │
      YES
       │
       ▼
Keep requested SKU as the reference
       │
       ▼
Only negotiate when another candidate
clears the safety gates and the strict
improvement threshold.
```

When the baseline is infeasible, recovery levers such as quantity, timing, price, or substitution can become legitimate paths to a safe transaction.

This rule prevents the nonsensical outcome of:

> “You increased the budget, so we replaced the product you asked for.”

---

# Monte Carlo reasoning

MIRROR does not assume that an uncertain transaction has one guaranteed outcome.

Conceptually:

```text
Candidate
   ↓
Sample uncertain outcomes
   ↓
Repeat simulations
   ↓
Outcome distribution
   ↓
Expected value + downside estimate
   ↓
P05 gate
```

**Expected net** describes the candidate's average economic outcome.

**P05** provides a downside-oriented view of the simulated distribution.

That distinction matters because a transaction can look attractive on average while still exposing the merchant to an unacceptable downside tail.

---

# Experimental ML safety layer

MIRROR includes a learned SLA-risk model as a second line of defence.

### Model

- Model: `sla-logreg-v1-seed-20260825`
- Type: Regularized Logistic Regression
- Target: SLA-miss probability
- Evaluation: SKU-held-out synthetic evaluation
- Held-out rows: **20,000**
- Safety threshold: **0.35**

### Persisted evaluation

| Metric | Result |
| --- | ---: |
| Precision | **65.64%** |
| Recall | **99.90%** |
| F1 | **79.23%** |
| Brier score | **0.052** |
| ECE | **12.66%** |
| Risk separation | **8.19×** |

The high recall is useful for a safety layer whose primary purpose is to catch risky cases.

### End-to-end experiment

- **2 / 500** decisions changed
- End-to-end change: **0.4%**
- Expected contribution change: **-0.84%**
- P05 change: **-0.59%**
- Extra ML rejects: **36**

These are experimental results on synthetic data, **not claims of production ROI**.

### Demonstration cases

**Risk caught:** an existing NEGOTIATE outcome is blocked when the predicted SLA-miss risk is high.

**Safer alternative:** an existing substitution is replaced by a price alternative after the ML safety check, with the old and new expected values exposed so the safety/value trade-off is visible.

---

# Locked benchmark evidence

The dashboard is backed by persisted deterministic experiment records.

- **500** persisted buyer requests
- Five deterministic seeds
- **4,108** total candidates evaluated
- **3,698** negotiation/alternative candidates entering the P05 aggregate
- **2,477** P05 failures
- **1,221** P05 survivors
- **390 ACCEPT**
- **55 NEGOTIATE**
- **55 REJECT**
- **35 / 45** constraint-conflict requests recovered
- **77.78%** constraint recovery rate

These figures describe the locked synthetic MIRROR experiment and are not guaranteed production performance.

---

# Negotiation intelligence

Negotiation is not limited to price reduction. MIRROR can use different recovery levers depending on the constraint conflict.

Persisted selected-lever evidence:

| Lever | Count | Share |
| --- | ---: | ---: |
| Substitution | 39 | 70.9% |
| Quantity | 15 | 27.3% |
| Timing | 1 | 1.8% |
| Price | 0 | 0.0% |

These numbers describe the persisted evidence set, not a universal marketplace rule.

---

# Decision states

### ACCEPT

The requested transaction is feasible and remains the safest selected outcome. MIRROR does not force negotiation simply because alternatives exist.

### NEGOTIATE

The baseline is infeasible or a better candidate satisfies MIRROR's strict decision rule. The selected recovery path must survive the relevant safety gates.

### REJECT

No acceptable safe transaction remains under the configured decision rules.

---

# Constraint recovery

A failed request does not automatically mean rejection.

```text
REQUEST
   │
   ├── price adjustment
   ├── quantity adjustment
   ├── timing adjustment
   └── SKU substitution
           │
           ▼
      candidate evaluation
           │
           ▼
      Monte Carlo + P05
           │
           ▼
        ML safety
           │
           ▼
       safe recovery
```

The locked experiment recovered **35 of 45** constraint-conflict requests, producing a **77.78%** rescue rate.

---

# Request Explorer

The dashboard includes a persisted request ledger so reviewers can inspect individual ACCEPT, NEGOTIATE, and REJECT cases rather than seeing only aggregate statistics.

This turns the demo into an evidence-driven journey through the system instead of a single polished result.

---

# Performance vs baseline

The dashboard reports mean uplift across five deterministic seeds against the persisted baseline reference.

MIRROR intentionally does not describe this as guaranteed profit or production ROI. The benchmark is synthetic and deterministic so the experiment can be reproduced consistently.

---

# Payment boundary

MIRROR separates **decision** from **payment execution**.

A recommendation is not presented as a completed financial transaction.

When checkout is demonstrated, Razorpay test credentials are used and payment signatures are verified server-side.

---

# Architecture

```text
                         BUYER REQUEST
                              │
                              ▼
                  ┌──────────────────────┐
                  │ DETERMINISTIC ENGINE │
                  └──────────┬───────────┘
                             │
                 ┌───────────┴───────────┐
                 │                       │
                 ▼                       ▼
          Candidate search       Constraint check
                 │                       │
                 └───────────┬───────────┘
                             ▼
                      MONTE CARLO
                             │
                             ▼
                         P05 GATE
                             │
                             ▼
                     P05 SURVIVORS
                             │
                             ▼
                       ML SLA GATE
                             │
                             ▼
                      SAFE SURVIVORS
                             │
                             ▼
                   FINAL DECISION LOGIC
                             │
                  ┌──────────┼──────────┐
                  ▼          ▼          ▼
               ACCEPT    NEGOTIATE    REJECT
                             │
                             ▼
                     PAYMENT BOUNDARY
```

### Responsibility split

| Layer | Responsibility |
| --- | --- |
| Deterministic engine | Economic logic, constraints, candidate evaluation and transaction selection |
| Monte Carlo | Uncertainty simulation |
| P05 gate | Downside-risk filtering |
| ML layer | SLA-miss probability and second safety veto |
| Frontend | Interactive decision room, evidence and visual explanation |
| Payment boundary | Optional transaction execution after recommendation |

---

# Project structure

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
│
├── data/
├── experiments/
│
├── frontened/
│   ├── index.html
│   ├── app.js
│   ├── app.css
│   ├── live-room.css
│   ├── tokens.css
│   ├── intelligence-core.js
│   ├── decision-pipeline.js
│   └── assets/
│
├── docs/
│   ├── FINAL_DEMO_QA.md
│   └── LIVE_DECISION_ROOM.md
│
├── render.yaml
├── requirements.txt
└── README.md
```

---

# Tech stack

### Backend

- Python
- FastAPI
- Uvicorn
- NumPy
- Pandas

### Decision & intelligence

- Deterministic decision rules
- Monte Carlo simulation
- P05 downside-risk filtering
- Regularized Logistic Regression
- Feature-based SLA-risk prediction

### Frontend

- HTML
- CSS
- JavaScript
- Interactive Live Decision Room
- Cinematic, section-based visual storytelling

### Deployment

- Render
- ASGI entrypoint: `backend.ai_app:app`

### Payments

- Razorpay test environment

---

# API

The live application is served through `backend.ai_app:app`.

Important endpoints:

```text
GET  /ai/risk/model
POST /ai/risk/predict
POST /ai/live-decision
```

`/ai/live-decision` combines the deterministic MIRROR pipeline with the live ML SLA-risk safety gate. The persisted 500-request experiment remains separate.

---

# Run locally

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start the complete application:

```powershell
uvicorn backend.ai_app:app --host 0.0.0.0 --port 8002
```

Open:

```text
http://127.0.0.1:8002/
```

Use `backend.ai_app:app`, not only `backend.main:app`, when you need the Live Decision Room and ML safety endpoints.

---

# Render deployment

The repository's Render configuration uses:

```text
uvicorn backend.ai_app:app --host 0.0.0.0 --port $PORT
```

with:

```text
/ai/risk/health
```

as the health-check path.

If a manually configured Render service still starts `backend.main:app`, switch it to the AI/live entrypoint before redeploying.

---

# Payment configuration

For payment testing, configure server-side Razorpay test credentials:

```text
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
```

Never commit credentials to the repository.

---

# Evidence & limitations

MIRROR is deliberately transparent about what its numbers mean.

- The benchmark uses synthetic MIRROR demand scenarios.
- The persisted experiment is deterministic and reproducible.
- The ML evaluation uses SKU-held-out synthetic data.
- The ML layer is a safety signal, not proof of real-world production performance.
- The five-seed performance result is not a guarantee of future profit.
- A recommendation is not the same as a completed payment.

The purpose of the project is to demonstrate **decision quality, risk awareness, explainability, and system architecture** without hiding uncertainty behind impressive-looking numbers.

---

# The idea in one sentence

> **MIRROR does not search for the deal that looks best — it searches for the deal that remains safe after uncertainty, downside risk, and SLA risk are taken into account.**

---

## Project status

**MIRROR — final interactive decision-engine demo**

The repository contains the deterministic decision engine, Monte Carlo evaluation, P05 downside gate, live ML SLA-risk safety layer, interactive decision room, persisted benchmark evidence, request exploration, and payment boundary for the end-to-end demonstration.

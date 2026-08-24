# MIRROR

### Merchant AI Commerce Intelligence

> **Find the transaction that survives the risk.**

MIRROR is a decision engine for commerce transactions under uncertainty. Instead of treating a buyer request as a simple accept/reject problem, MIRROR evaluates whether the transaction can be **recovered, negotiated, or safely declined** while protecting downside risk.

The project combines a persisted five-seed experiment, a data-driven decision pipeline, an evidence-first explorer, and a cinematic product interface.

---

## The idea

A commerce request can fail for many reasons: inventory constraints, timing, price pressure, or unacceptable downside. MIRROR searches the space of legitimate alternatives and keeps only candidates that survive the persisted risk gate.

```text
BUYER REQUEST
      │
      ▼
┌───────────────┐
│  BASELINE     │──── feasible ────► ACCEPT when no safe improvement wins
│  EVALUATION   │
└───────┬───────┘
        │ pressure / conflict
        ▼
┌──────────────────────┐
│ CANDIDATE SEARCH     │
│ price / substitution │
│ quantity / timing    │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ P05 RISK GATE        │
│ reject unsafe paths  │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ SURVIVING CANDIDATE  │
│ highest-scoring safe │
│ alternative          │
└──────────┬───────────┘
           ▼
       DECISION
     /     |      \
 ACCEPT  NEGOTIATE  REJECT
                 
           ▼
     RAZORPAY BOUNDARY
```

The important distinction is that the interface **does not invent an AI narrative**. Visual states and displayed metrics are driven by persisted experiment records and their actual fields.

---

## What is in the experience

### Cinematic opening

A fullscreen MIRROR opening sequence establishes the product before the dashboard appears. The supplied local video is served from the frontend and hands off into the live dashboard when it ends; the intro can also be skipped.

### Decision pipeline

The interface visualizes the journey from baseline pressure through candidate search, uncertainty, survival, and the final decision. Candidate persistence, risk-gate outcomes, and the selected candidate come from the stored experiment records.

### Evidence, not dashboard noise

The later sections deliberately become more restrained:

- **Value Created** — five-seed value evidence
- **Constraint Recovery** — recovery/rescue evidence
- **Risk Protection** — P05 gate evidence
- **Negotiation Levers** — actual selected lever counts
- **Request Explorer** — the persisted 500-request decision ledger
- **Execution Boundary** — the handoff from MIRROR intelligence to Razorpay

### Decision states

MIRROR supports three persisted outcomes:

| Decision | Meaning |
| --- | --- |
| **ACCEPT** | The baseline remains the safe selected transaction. |
| **NEGOTIATE** | A risk-gate-passing alternative beats the baseline under the decision rule. |
| **REJECT** | No candidate satisfies the persisted decision rule. |

---

## Data integrity principle

**The visuals are allowed to be expressive. The evidence is not.**

The dashboard reads audited experiment artifacts rather than regenerating presentation numbers. The backend indexes persisted request/decision records and exposes read-only dashboard endpoints for the frontend.

The runtime model includes:

- five experiment seeds
- persisted buyer requests
- candidate evaluations
- `passes_risk_gate`
- expected contribution
- P05 downside values
- selected candidates
- recovery outcomes
- negotiation-lever aggregates
- request-level decision records

No fabricated progress percentages, fake AI reasoning, or simulated payment-success states are part of the product narrative.

---

## Architecture

```text
                    ┌────────────────────────┐
                    │     MIRROR FRONTEND     │
                    │ HTML / CSS / JS / SVG   │
                    └───────────┬────────────┘
                                │
                                │ /dashboard/*
                                ▼
                    ┌────────────────────────┐
                    │       FASTAPI          │
                    │ persisted API surface  │
                    └───────────┬────────────┘
                                │
             ┌──────────────────┼──────────────────┐
             ▼                  ▼                  ▼
      ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
      │ buyer data  │   │ experiments  │   │ decision /   │
      │ CSV         │   │ JSON records  │   │ payment flow │
      └─────────────┘   └──────────────┘   └──────┬───────┘
                                                   │
                                                   ▼
                                           Razorpay Test Mode
```

### Frontend

The frontend lives under `frontened/` and includes the cinematic intro, core MIRROR visual system, decision-pipeline visualization, explorer, and execution boundary.

### Backend

`backend/main.py` serves the dashboard APIs and static UI surface. Persisted experiment artifacts are loaded from `experiments/` and buyer-request records from `data/`.

### Payment boundary

Razorpay order creation is server-side and only available when test credentials are configured. Selected negotiation candidates are validated against persisted records before an order can be created, and payment signatures are verified server-side.

---

## Project structure

```text
MIRROR/
├── backend/
│   ├── main.py
│   └── test_dashboard.py
├── data/
│   └── persisted buyer-request data
├── experiments/
│   ├── persisted seed results
│   ├── five-seed summary
│   └── experiment analysis
├── frontened/
│   ├── index.html
│   ├── app.js
│   ├── app.css
│   ├── tokens.css
│   ├── intelligence-core.js
│   ├── intelligence-core.css
│   ├── decision-pipeline.js
│   ├── decision-pipeline.css
│   ├── core-overrides.css
│   ├── cinematic-intro.css
│   └── assets/
│       ├── mirror-vessel.svg
│       └── MIRROR — Commerce Decision Engine_processed.mp4
└── README.md
```

---

## Run locally

### 1. Create / activate the virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

Use the project's dependency setup if present in your environment.

### 3. Start MIRROR

```powershell
python backend/main.py
```

Then open the local UI at the port configured by the backend, for example:

```text
http://127.0.0.1:8002/
```

The backend also exposes `/health` for a basic service check.

---

## Payment configuration

Razorpay is intentionally treated as an execution boundary rather than as part of the decision engine.

Set test credentials in the server environment when payment testing is required:

```text
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
```

Never commit credentials to the repository.

When credentials are absent, the interface should remain truthful and show the disabled/no-credentials state rather than pretending a payment succeeded.

---

## Validation philosophy

The project has been checked across desktop and mobile compositions, including:

- 1440×900
- 1280×720
- 768×720
- 390×844

Key regression checks include:

- 10 dashboard sections
- 500 persisted explorer rows
- ACCEPT / NEGOTIATE / REJECT states
- no horizontal overflow
- cinematic intro handoff
- reduced-motion behavior
- persisted-data bindings
- Razorpay disabled-state behavior

---

## Visual direction

MIRROR is intentionally **not** styled as a conventional AI dashboard.

The visual language is built around a precision instrument: restrained indigo/blue atmosphere, dimensional geometry, sparse symbols, asymmetric composition, and state-driven motion. The interface should feel closer to an engineered commerce instrument than a generic SaaS control panel.

The governing rule is simple:

> **Story can be expressive. Evidence must remain real.**

---

## Status

**Active build — `mirror-visual-redesign`**

Current milestones:

- Persisted experiment-backed dashboard APIs
- Data-driven decision pipeline
- MIRROR vessel visual system
- Cinematic opening sequence
- Responsive hero refinement
- Razorpay test-mode execution boundary

---

## Repository

urlMIRROR on GitHubhttps://github.com/SHIVAIN-MITTAL16/MIRROR

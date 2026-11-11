# MIRROR — AI Purchase Assurance

> **Your receipt remembers what you paid. MIRROR remembers what you were promised.**

MIRROR is a buyer-first AI Purchase Assurance prototype for electronics purchases.

The primary workflow is Gemini buyer-intent extraction, explicit buyer review, Passport creation, seller offer/evidence collection, deterministic evaluation, and decision-gated PayPal sandbox checkout. Gemini only proposes buyer conditions; it does not verify evidence or decide whether payment is safe. A narrow server-side Channel3 verifier can support only unambiguous catalogue facts. Seller-uploaded evidence remains unverified, and catalogue data never proves seller fulfilment.

Buyer and seller accounts now use Argon2 password hashes and expiring, revocable server-side sessions. Passports are buyer-owned; a buyer grants Passport-scoped access to a registered seller account ID, and the seller must accept before seeing buyer-shared conditions or submitting an offer. Account registration does not independently verify a person's real-world identity or email ownership. Channel3 verification covers a limited set of product catalogue facts and does not verify physical items, warranty, delivery, returns, or fulfilment. Seller-uploaded evidence remains unverified. This remains a controlled prototype, not production-ready.

For launch commands, API payloads, configuration, and limitations, see [Purchase Assurance MVP](#purchase-assurance-mvp-current-local-prototype). Editable unit economics are in [Business Model Projection](docs/business-model.html). Import the [Postman collection](postman/MIRROR-Purchase-Assurance.postman_collection.json) and placeholder [local environment](postman/MIRROR-Local.postman_environment.json); neither contains credentials.

## Current buyer-facing APIs

```text
GET    /health
POST   /api/passport-intents/extract
POST   /api/passports/confirm-intent
POST   /api/passports
GET    /api/passports
GET    /api/passports/{passport_id}
POST   /api/passports/{passport_id}/conditions
POST   /api/passports/{passport_id}/offers
GET    /api/passports/{passport_id}/offers
POST   /api/passports/{passport_id}/evidence
GET    /api/passports/{passport_id}/evidence
GET    /api/passports/{passport_id}/evidence/{evidence_id}
POST   /api/passports/{passport_id}/evaluate
POST   /api/passports/{passport_id}/disputes
GET    /api/passports/{passport_id}/disputes
GET    /api/products/config
POST   /api/products/search
GET    /api/products/{product_id}
GET    /api/paypal/config
POST   /api/passports/{passport_id}/paypal/order
POST   /api/passports/{passport_id}/paypal/capture
POST   /api/passports/{passport_id}/paypal/cancel
POST   /api/paypal/webhooks
```

The former merchant inventory and ML experiment is collapsed below and is not the buyer product. Its `/ai/*` and `/dashboard/*` APIs remain experimental.

<details>
<summary>Historical merchant decision-engine experiment (not MIRROR's current buyer product)</summary>

### Legacy merchant decision-engine experiment

> **Find the transaction that survives the risk.**

MIRROR is a **risk-aware commerce decision system** for transactions where price, inventory, quantity, delivery time, demand uncertainty, and service-level risk can change the outcome.

Instead of only asking *“Can we sell this?”*, MIRROR asks:

> **“Which transaction is still safe when uncertainty is taken seriously?”**

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

Purchase Passport checkout uses the PayPal Orders API in sandbox mode. The server creates and captures orders, rechecks the Passport decision before capture, and records the confirmed capture reference. No payment is described as successful until PayPal reports a completed capture.

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

- PayPal sandbox Orders API and JavaScript SDK

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

## Purchase Passport persistence (Phase 1)

The buyer Purchase Passport API stores passports and buyer conditions in a local SQLite database. The database is initialized when the FastAPI application starts. By default, the file is `data/mirror.sqlite3`; set `MIRROR_DATABASE_PATH` to choose another location. The database file is excluded from version control.

Available endpoints:

```text
POST /api/passports
GET  /api/passports
GET  /api/passports/{passport_id}
POST /api/passports/{passport_id}/conditions
POST /api/passports/{passport_id}/evaluate
POST /api/passports/{passport_id}/offers/{offer_id}/catalogue-verification
POST /api/passport-intents/extract
POST /api/passports/{passport_id}/evidence
GET  /api/passports/{passport_id}/evidence
GET  /api/passports/{passport_id}/evidence/{evidence_id}
```

Create a passport with `{"buyer_intent":"A sealed camera delivered by Friday","currency":"USD"}`. Conditions are submitted as a JSON array with `condition_type`, `operator`, `expected_value`, and `hard_or_soft`. `owner` accepts `buyer` or `merchant` and defaults to `buyer` for older clients. The ordinary condition endpoint ignores client-supplied confirmation flags and always creates unconfirmed conditions. Use the explicit buyer-review confirmation endpoint below to persist buyer-confirmed conditions. The database migration assigns existing conditions to the buyer and preserves their existing `buyer_confirmed` values without inventing historical confirmation timestamps. Timestamps are stored in UTC. Passport checkout stores PayPal order and capture references, request idempotency identifiers, and payment state, but never payment credentials or access tokens. Fulfilment events have an `is_simulated` marker so simulated data remains distinguishable from real evidence.

Condition evaluation supports `price`, `quantity`, `delivery_days`, `ram`, and `storage_capacity` with numeric comparison operators; `product_name`, `seller_name`, `currency`, `return_terms`, `item_condition`, `sku_id`, `brand`, `model`, `processor_family`, `display_resolution`, and `operating_system` support `eq` and `ne`. Other types and operators are reported unresolved. Evidence must be linked to the exact condition and claim; simulated evidence never counts as verification. The evaluation endpoint accepts no client-supplied evidence or verification data. It returns `APPROVE`, `NEGOTIATE`, `REJECT`, or `ESCALATE`, with condition-level passed, failed, and unresolved explanations.

### Evidence ingestion (Stage 1)

`POST /api/passports/{passport_id}/evidence` accepts JSON text content with `text/plain` or `application/json`, optional claimed source metadata, and optional `condition_ids` from the same Passport. Content is limited to 64 KiB of UTF-8. MIRROR stores the original text, computes SHA-256, and records server `received_at` separately from the untrusted optional `claimed_captured_at`. The digest is an integrity reference, not proof of who created the content or where it came from. Ingestion always creates `lifecycle_state=raw` and `verification_status=unverified`; it does not create claims or fetch source URLs.

Evidence list/detail responses omit original content by default. A detail request can explicitly ask for text using `?include_content=true`. There is no generic client-controlled verification route. The dedicated Channel3 catalogue-verification endpoint is server-side and accepts only a product ID and refresh flag; clients cannot submit verification status or claims. Claims are usable by the evaluator only when linked to the condition, scoped to that exact condition type, non-simulated, and backed by a verified server event. Raw evidence alone cannot pass a condition.

Verification events, claims, and condition-to-evidence associations are append-only in SQLite. Evidence lifecycle/status updates require a matching latest `server_verifier` event, including verifier identity, verifier version, timestamp, outcome, reason, and the exact claim scope. The Channel3 adapter follows this audit flow atomically. It records the server-retrieved product response and digest; the digest does not prove who authored the provider data. Existing migration backfills remain unverified and do not infer claims.

Passport APIs require a registered buyer or seller session. Buyer routes check Passport ownership. Sellers can access only Passports where the buyer created a grant for the seller account ID and the seller accepted it. Grant revocation blocks further seller access. Existing Passports and offers migrate with null ownership and are not listed or accessible through authenticated owner routes; ownership is never inferred from IDs or free-text seller names. The local locked catalog and inventory data are synthetic and must remain labelled simulated rather than treated as trusted merchant evidence.

### Buyer intent extraction and confirmation (Phase 1)

`POST /api/passport-intents/extract` accepts `{"text":"I need a laptop under ₹80,000 delivered within five days."}` and returns unpersisted condition proposals, clarification questions, and a `ready_for_review` flag. Gemini uses JSON structured output, followed by server-side validation against supported Passport condition types/operators and the original text. Every returned proposal includes a supporting quote that must be an exact substring; numeric values, comparison wording, currencies, and units are checked against that quote. Unsupported or ambiguous requirements produce clarification questions. This endpoint creates no Passport, condition, evidence, confirmation, or claim.

After the buyer reviews and edits the proposals, `POST /api/passports/confirm-intent` accepts the reviewed values and an explicit acknowledgement. Example request:

```json
{
  "buyer_intent": "I need a new camera under 800 USD",
  "currency": "USD",
  "buyer_acknowledged": true,
  "conditions": [
    {"condition_type":"price","operator":"lte","expected_value":"800","unit":"USD","hard_or_soft":"hard","supporting_quote":"under 800 USD"},
    {"condition_type":"item_condition","operator":"eq","expected_value":"new","unit":null,"hard_or_soft":"hard","supporting_quote":"new camera"}
  ]
}
```

The endpoint validates each type/operator pair, numeric values, classification, and exact supporting quote, then creates the Passport and all buyer-owned confirmed conditions in one SQLite transaction. The authenticated buyer becomes Passport owner. The response contains conditions with `owner: "buyer"`, `buyer_confirmed: true`, and a UTC `buyer_confirmed_at`. Empty or invalid condition sets are rejected. This records a declaration by the currently authenticated account; it does not independently verify the user's real-world identity. No Gemini request or evidence verification occurs in this operation.

Set `GEMINI_API_KEY` in the process environment or the ignored repository `.env` file. `GEMINI_MODEL` optionally selects the model; the current default is `gemini-3.5-flash-lite`. API keys are never stored in SQLite or returned in responses. Missing configuration and transient network/timeout failures return an explicitly labelled empty fallback with no proposals. Invalid structured output and permanent provider failures return generic errors. Do not send buyer text containing sensitive personal information unless permitted by the deployment's privacy policy.

Example evaluation request:

```http
POST /api/passports/abc123/evaluate
```

Example response (evidence omitted from this illustrative shape):

```json
{
  "passport_id": "abc123",
  "outcome": "ESCALATE",
  "passed_conditions": [],
  "failed_conditions": [],
  "unresolved_conditions": [
    {"condition_id": "condition-1", "owner": "buyer", "condition_type": "item_condition", "operator": "eq", "expected_value": "sealed", "observed_values": [], "hard_or_soft": "hard", "status": "unresolved", "evidence_ids": [], "evidence_statuses": [], "simulated_evidence_ids": [], "confirmation_required": "buyer_confirmed", "confirmation_received": true, "reasons": ["evidence_missing_or_unlinked"]}
  ],
  "reasons": ["Required confirmation or trustworthy, unambiguous evidence is unresolved."],
  "ml_assessment": {"applied": false, "reason": "Required confirmed, verified SKU, quantity and delivery_days conditions are unavailable."}
}
```

Run the persistence tests with:

```powershell
python -m unittest backend.test_passports
python -m unittest discover -s backend -p "test*.py"
```

The first command runs the new Passport API tests; the second runs the complete backend test suite.

---

### Historical launch note (superseded)

The current local launch procedure is in the Purchase Assurance MVP section below. The API is not the frontend UI; open the static frontend at `http://127.0.0.1:5501`.

---

# Render deployment

The repository includes a Render Blueprint for separate FastAPI and static frontend services, a persistent SQLite disk, exact frontend CORS origin, and a public API base injected into the static build. This is deployment configuration only; no deployment was performed or verified. Add the Blueprint to Render, provide the prompted secrets, and check the resulting service URLs before using it.

The backend command is:

```text
uvicorn backend.ai_app:app --host 0.0.0.0 --port $PORT
```

and health check:

```text
/health
```

as the configured health-check path. No deployment has been verified.

The static site is built by `scripts/build_frontend.py`. `CHANNEL3_API_KEY` is optional and enables product discovery. No product provider credentials are exposed to the browser.

---

# Payment configuration

For Passport checkout, configure server-side PayPal sandbox credentials:

```text
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=...
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
</details>

# Purchase Assurance MVP (current local prototype)

The buyer-first flow uses the existing Gemini extraction and explicit buyer confirmation APIs, then lets a seller submit an offer and text evidence against every buyer condition. Evidence is preserved with a server received timestamp and SHA-256 digest. Seller submitted evidence remains raw/unverified; MIRROR does not claim that it proves the seller's statements.

Buyer and seller accounts use Argon2 password hashes and 12-hour, revocable server-side sessions. Registration is self-service and does not verify email ownership or real-world identity. A buyer grants access to a specific registered seller account ID; the seller must accept the expiring grant before viewing the buyer-shared conditions or submitting an offer. Existing database Passports and offers remain unowned and are not assigned to accounts.

## Start locally

From the repository root, create the virtual environment once, install dependencies, and run the backend:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.ai_app:app --host 127.0.0.1 --port 8002
```

In a second terminal, serve the existing frontend:

```powershell
python -m http.server 5501 --directory frontened
```

After creating `.venv` and installing dependencies once, both services can be started with one command: `powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1`.

Open `http://127.0.0.1:5501`. Register a buyer account, create a Passport, then separately register or sign in as a seller in another browser profile/context. Copy the seller account ID displayed after sign-in, return to the buyer session, select the Passport, and grant access to that ID. The seller accepts the grant in their session before submitting an offer. The buyer reviews evidence and evaluates the Passport. Development CORS allows that exact origin. Set `MIRROR_CORS_ORIGINS` to comma-separated exact origins for a different frontend host. `MIRROR_API_BASE_URL` can override the frontend API base before page load; the local default is `http://127.0.0.1:8002`.

## Browser QA on Windows

Install the JavaScript test dependency and Playwright Chromium once:

```powershell
npm install
npx playwright install chromium
```

Run browser tests from a PowerShell terminal:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-browser.ps1
```

The script starts the backend and static frontend on free loopback ports, waits for health checks, and uses a newly created temporary SQLite database that is removed afterward. It does not take over existing services. Failure screenshots, traces, videos, and browser diagnostics are written under `test-results/browser`; the HTML report is under `playwright-report`. Channel3 product search and catalogue verification run live when `CHANNEL3_API_KEY` is available in the ignored `.env`; otherwise the live product test is reported as skipped after checking the configuration-required UI state. Gemini extraction uses an explicitly marked browser-test response, and the test never creates or captures a PayPal order.

## Environment variables

- `GEMINI_API_KEY` is required for live buyer intent extraction.
- `GEMINI_MODEL` optionally overrides the default `gemini-3.5-flash-lite`.
- `GEMINI_TIMEOUT_MS` optionally configures the Gemini provider timeout; default is 45000.
- `MIRROR_DATABASE_PATH` optionally selects the SQLite file; default is `data/mirror.sqlite3`.
- `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` enable Passport checkout. `PAYPAL_BASE_URL` defaults to `https://api-m.sandbox.paypal.com`; configure sandbox credentials for the demo. Only the public client ID is sent to the official PayPal JS SDK; the secret stays on the backend.
- PAYPAL_WEBHOOK_ID enables signature-verified webhook reconciliation after registering a webhook in the PayPal sandbox developer application.
- CHANNEL3_API_KEY is optional and enables the documented Channel3 search/details adapter. Without it, product discovery reports configuration required.
- MIRROR_API_BASE_URL defaults to http://127.0.0.1:8002; the deployment build injects the static frontend API origin.
- `MIRROR_CORS_ORIGINS` defaults to the local frontend and `https://mirror-ui-cl6q.onrender.com`; credentialed CORS is limited to these explicit origins. Set the exact deployed UI origin for other deployments. HTTPS auth cookies use `SameSite=None; Secure`; the authenticated session response supplies the CSRF token to the frontend, which continues sending `X-Mirror-CSRF` on mutations.

## Deterministic demo journey

1. Enter a synthetic buyer request in Buyer Intent, extract proposals, resolve clarifications, review every value, and explicitly confirm it.
2. Inspect the saved Passport in Purchase Assurance.
3. In a separate seller session, accept the buyer's Passport-specific grant. Submit an offer, confirm or decline every buyer condition, and attach seller text. The API preserves it as unverified evidence.
4. Evaluate the selected offer and inspect condition-level reasons, provenance, and audit history.
5. `Start / replay labelled demo` creates a new `[DEMO]` buyer Passport only. Use the separate seller session and grant handoff above to submit an offer; this button does not impersonate a seller or generate seller evidence. Existing audit records are not deleted.
6. PayPal checkout is available only if the server evaluation returns `APPROVE` and PayPal sandbox configuration is present.

## Prototype limitations

Sessions and Passport ownership are enforced for application routes, but account registration does not verify email ownership or real-world buyer/seller identity. There is no password recovery, email verification, or authentication rate limiting. Historical Passports/offers remain unowned and cannot be claimed through the API. Channel3 can support only product title/identity, unambiguous brand/model, and explicitly returned technical specifications (processor family, display resolution, operating system, RAM, and storage capacity with matching units). The provider response does not establish that the seller's physical item is the catalogue item. Price, delivery, warranty, physical condition, return terms, seller reliability, and fulfilment remain unresolved unless a suitable independent verifier is added. Seller uploads alone cannot satisfy conditions. PayPal currently charges the displayed offer amount; shipping, taxes, and additional disclosed charges are not modeled. This is a controlled prototype, not production-ready multi-user software.

# MIRROR — AI System Specification + Buildathon Control

**Version:** 1.0  
**Date:** 25 August 2026  
**Working branch:** `mirror-visual-redesign`

> **North-star:** Can MIRROR recover or preserve commerce value while proving that its chosen action survives its own failure analysis and explicit financial safety constraints?

---

## 1. Executive Decision

MIRROR is being repositioned from a simulation-backed commerce decision dashboard into a genuine **AI Commerce Recovery & Risk Agent**.

The existing system is the foundation:

- persisted five-seed experiment
- locked demand/inventory data
- Monte Carlo candidate evaluation
- P05 downside metrics
- candidate search
- risk-gate decisions
- persisted request explorer
- FastAPI APIs
- Razorpay test-mode execution boundary
- explainable visual decision pipeline

The next build adds the missing AI and safety layers:

**predictive ML → agentic tool use → simulation → adversarial attack → policy → bounded execution → observed outcome → evaluation**

### Non-negotiable truth rule

The AI may reason, plan and explain. It may **not invent financial facts**. Numbers must come from runtime data, model outputs, simulations, policies or execution results.

---

## 2. Current System — What Is Already Real

### Data and simulation

- Locked 50-SKU demand/inventory dataset with validation.
- Persisted experiment records and five-seed summary.
- Monte Carlo decision evaluation using 10,000 paths.
- Empirical demand CDF cache.
- P05 downside calculations.
- Candidate evaluation across price, quantity, timing and substitution.

### Decision engine

- Baseline feasibility evaluation.
- Candidate search.
- Persisted risk-gate result.
- Selected surviving candidate.
- `ACCEPT` / `NEGOTIATE` / `REJECT` decision states.

### Product

- FastAPI dashboard APIs.
- Request explorer and persisted decision ledger.
- Cinematic introduction and MIRROR vessel visual system.
- Responsive dashboard.
- Intro replay persistence.
- Razorpay test-mode boundary with server-side order/payment handling.

### Evidence principle

> **Story can be expressive. Evidence must remain real.**

---

## 3. New Product Definition

# MIRROR — An AI Commerce Recovery & Risk Agent

Given a commerce event under uncertainty, MIRROR:

1. understands the transaction context;
2. predicts relevant risks;
3. generates bounded interventions;
4. simulates their downside;
5. attacks its own proposed decision;
6. applies explicit policy limits;
7. executes only an allowed action;
8. records the outcome;
9. evaluates whether the intervention actually preserved/recovered value.

MIRROR should not be a chatbot wrapped around a dashboard. The LLM is one component inside a controlled decision system.

---

## 4. Target Architecture

```text
                         COMMERCE EVENT
                               │
                               ▼
                 ┌────────────────────────┐
                 │ AI UNDERSTANDING       │
                 │ structured state       │
                 │ intent + context       │
                 └────────────┬───────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ ML RISK PREDICTOR      │
                 │ calibrated probabilities│
                 └────────────┬───────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ CANDIDATE GENERATOR    │
                 │ retry / substitution   │
                 │ price / quantity / SLA │
                 └────────────┬───────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ MIRROR SIMULATION      │
                 │ Monte Carlo / P05      │
                 └────────────┬───────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ ADVERSARIAL AI         │
                 │ "How can this fail?"   │
                 └────────────┬───────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ FAILURE GRAPH           │
                 │ cascade + exposure     │
                 └────────────┬───────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ POLICY / DECISION       │
                 │ CONTRACT                │
                 └────────────┬───────────┘
                       unsafe │       │ safe
                              ▼       ▼
                       HOLD/HUMAN  EXECUTION
                                      │
                                      ▼
                              RAZORPAY TEST MODE
                                      │
                                      ▼
                               OBSERVED OUTCOME
                                      │
                                      ▼
                              AUDIT + EVALUATION
```

---

## 5. Real AI Components

### 5.1 Predictive ML Risk Model

Build a genuine model for:

- probability of revenue loss
- probability of payment failure
- probability of SLA miss
- probability of return

Use separate train/validation/held-out test data.

Required measurements:

- precision
- recall
- F1
- PR-AUC / ROC-AUC where appropriate
- calibration
- false-positive cost
- false-negative cost

A model is not considered complete until it has a reproducible held-out evaluation.

### 5.2 Agentic Reasoning Layer

The agent uses tools instead of hallucinating facts.

Core tools:

```text
get_transaction()
get_inventory()
predict_risk()
generate_candidates()
run_simulation()
attack_decision()
calculate_exposure()
check_policy()
```

The agent can understand, plan, select tools and explain. Deterministic services provide facts and the policy layer controls financial actions.

### 5.3 Adversarial / Red-Team AI

Every material proposed action is challenged:

> **Assume the recommendation is wrong. How can it fail?**

The attack should look for:

- duplicate authorization
- duplicate order
- inventory reservation conflict
- stockout
- SLA miss
- return/refund exposure
- fraud exposure
- margin erosion
- liquidity pressure
- API timeout / ambiguous execution
- retry loops

The system then mitigates the discovered failure and re-evaluates the candidate.

---

## 6. Decision Contract

Every executable decision should have a machine-readable contract:

```text
decision_id
request_id
candidate_id
action
reason
expected_value
p05_downside
risk_probabilities
exposure_before
exposure_after
policy_checks
red_team_findings
mitigations
approval_required
execution_limit
model_versions
simulation_seed
evidence_refs
final_status
```

No payment action should execute without a valid contract that passes policy.

---

## 7. Execution Governor

The Execution Governor is deterministic and sits between AI reasoning and money movement.

It enforces:

- action allowlists
- maximum exposure
- approval thresholds
- idempotency
- rate limits
- test/live environment separation
- stopping rules
- ambiguous-state handling
- human escalation

**An LLM must never be able to bypass the governor.**

---

## 8. Worst-Case / Failure-First Design

The project must explicitly test the failure cases that normal demos avoid.

### Priority scenarios

1. Payment fails and retry is safe.
2. Payment fails and retry is unsafe.
3. Retry creates duplicate authorization risk.
4. Inventory is reserved twice.
5. Substitute becomes unavailable after selection.
6. Expected value improves while P05 downside becomes unacceptable.
7. Successful payment is followed by SLA miss and return.
8. Payment/API timeout leaves ambiguous execution state.
9. Duplicate request attacks idempotency.
10. Model drift makes the agent overconfident.
11. Agent proposes an action outside its monetary authority.
12. Repeated recovery attempts create a loss spiral.

### Failure cascade

```text
PAYMENT FAILURE
      │
      ├── RETRY
      │     ├── duplicate authorization
      │     │       ├── refund exposure
      │     │       └── support cost
      │     └── inventory re-reservation
      │             └── stockout
      │                    └── substitution
      │                           └── SLA miss
      │                                  └── return
      │                                         └── margin loss
      │
      └── SAFE ALTERNATIVE / HOLD
```

---

## 9. Evaluation System

| Layer | Metric | Evidence | Gate |
|---|---|---|---|
| ML risk model | Precision / Recall / F1 / calibration | Held-out set | Beat defined baseline |
| Agent | Tool correctness / policy compliance | Trace logs + replay | No unsafe tool call |
| Simulation | P05 / expected contribution | Seeded runs | Reproducible |
| Decision | Unsafe actions blocked | Failure benchmark | 100% for defined policy class |
| Recovery | Value recovered / exposure prevented | Batch outcomes | Measured, not narrated |
| Execution | Idempotency / bounded amount | Test-mode ledger | No duplicate execution |

### North-star product metrics

```text
Revenue at Risk Detected
Revenue Recovered
Exposure Prevented
Unsafe Actions Blocked
Transactions Survived
False Positive Cost
False Negative Cost
Agent Decisions Evaluated
Held-out Precision
Held-out Recall
```

---

## 10. Scenario Benchmark Suite

The benchmark must include at least:

- normal successful transaction
- payment failure with safe retry
- payment failure with unsafe retry
- inventory shortage + substitution
- deadline pressure + no feasible substitute
- high expected value + unacceptable P05 downside
- recovery followed by return
- ambiguous payment timeout
- duplicate-request/idempotency attack
- model drift / adversarial input

Every scenario should have deterministic inputs, a reproducible seed where stochastic simulation is involved, expected safety properties, and recorded results.

---

## 11. Observability and Audit

Every agent decision must be replayable from an immutable trace:

```text
input snapshot
    ↓
model version
    ↓
tool calls
    ↓
tool outputs
    ↓
candidate set
    ↓
simulation seed + outputs
    ↓
red-team findings
    ↓
policy result
    ↓
execution request
    ↓
execution result
    ↓
final outcome
```

This allows a reviewer to ask **what happened, what the AI knew, what it considered, what it rejected, why it acted, and what actually happened afterward.**

---

## 12. Product Surfaces

The final product should expose:

- live transaction/risk view
- decision pipeline
- candidate survival/rejection view
- counterfactual explorer
- failure cascade graph
- AI tool/reasoning trace with facts separated from generated explanation
- risk-model evaluation panel
- failure-injection scenario lab
- execution governor / approval state
- audit and replay ledger
- recovery and exposure metrics

---

## 13. Repository Control Structure

```text
docs/
├── MIRROR_AI_SYSTEM_SPEC.md       # canonical product + AI contract
├── CURRENT_STATE.md                # what actually works today
├── ARCHITECTURE.md                 # implementation architecture
├── AI_SYSTEM.md                    # ML + agent design
├── FAILURE_MODEL.md                # failure taxonomy + scenarios
├── EVALUATION.md                   # datasets + metrics + benchmarks
├── DATA_CONTRACT.md                # schemas + truth rules
├── SECURITY.md                     # execution + model safety
├── DEMO_SCRIPT.md                  # 5-minute pitch
├── BUILDATHON_CHECKLIST.md         # requirement tracker
└── CHANGELOG.md                    # implementation history
```

This document is the **canonical direction**. Other docs should describe implementation details and current evidence, not contradict it.

---

## 14. Buildathon Control Board

| Capability | Status |
|---|---|
| Public GitHub repository | DONE |
| Deployed product | DONE |
| Persisted decision system | DONE |
| Monte Carlo simulation | DONE |
| P05 risk gate | DONE |
| Explainable pipeline | DONE |
| Razorpay execution boundary | DONE |
| Real predictive ML | NEXT |
| Held-out evaluation | NEXT |
| Tool-using AI agent | NEXT |
| Adversarial AI | NEXT |
| Failure injection | NEXT |
| Decision Contract | NEXT |
| Execution Governor | NEXT |
| Audit trace | NEXT |
| Counterfactual explorer | NEXT |
| Recovery benchmark | NEXT |
| Shadow mode | NEXT |
| Drift detection | NEXT |
| Final 5-minute demo | NEXT |

**Rule:** a capability moves from NEXT to DONE only when it exists in code, has tests/evidence, and can be demonstrated.

---

## 15. Rules That Prevent Future Misery

1. Never claim an AI capability until it exists in code and has evidence.
2. Never allow the LLM to generate financial facts.
3. Never mix demo/static values with runtime values without labeling them.
4. Every major feature gets a document entry, test, and changelog entry.
5. Every model has a version and evaluation record.
6. Every execution is idempotent and auditable.
7. Every safety threshold is explicit and reviewable.
8. Every benchmark has reproducible inputs and seeds.
9. README claims must match the current branch.
10. The final demo must show one complete failure → reasoning → recovery → outcome story.

---

## 16. Implementation Order

### Phase 0 — Freeze baseline

Create `CURRENT_STATE.md`, capture current API/data/model behavior, and preserve a known-good commit.

### Phase 1 — Contracts

Implement schemas for:

- Decision Contract
- Risk Prediction
- Agent Trace
- Execution Result

### Phase 2 — Real ML

Build a deterministic baseline first, then train and evaluate the first real risk model on held-out data.

### Phase 3 — Agent

Add tool-calling around existing deterministic APIs.

### Phase 4 — Adversarial layer

Implement red-team attacks and failure-cascade graph generation.

### Phase 5 — Safety

Implement Policy Engine + Execution Governor + idempotency + human approval thresholds.

### Phase 6 — Evidence

Add scenario laboratory, audit/replay, counterfactuals, and recovery metrics.

### Phase 7 — Execution

Connect the controlled flow to Razorpay test mode, including ambiguous-state handling.

### Phase 8 — Competition readiness

Run the benchmark suite, freeze metrics, produce the 5-minute demo, then finalize README and visuals.

---

## 17. Definition of Done

MIRROR is ready when a reviewer can provide a transaction and watch the complete chain:

**event → AI understanding → real risk prediction → candidate actions → simulation → adversarial attack → policy gate → bounded execution → observed outcome → replayable evidence.**

If any displayed number cannot be traced to data, a model, a simulation, a policy check, or an execution result, it must not be presented as evidence.

---

## 18. Competition Alignment

The architecture is intentionally designed around the Razorpay Buildathon emphasis on real AI, working products, architecture, measurable outcomes, explainable financial actions, bounded execution, failure handling, and evaluation. The live competition requirements should be rechecked immediately before submission because external requirements can change.

---

## 19. Immediate Next Task

**Do not add another cosmetic feature.**

First implement the **Decision Contract + Risk Prediction schema + baseline ML evaluation harness**. That creates the backbone for the real AI layer and gives every later feature a place to plug in.

> **MIRROR: evidence over narrative; intelligence under constraints.**

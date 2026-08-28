# MIRROR Live Decision Room

## Purpose

The Live Decision Room lets a user enter a fresh buyer demand and receive a new MIRROR decision instead of only replaying one of the 500 persisted benchmark requests.

It is intentionally **not an LLM chatbot**. The request is converted into the same decision structure used by the benchmark and sent through the existing deterministic engine:

```text
FRESH DEMAND
    ↓
BASELINE CHECK
    ↓
CANDIDATE GENERATION
    ↓
MONTE CARLO
    ↓
P05 DOWNSIDE GATE
    ↓
SAFE SURVIVORS
    ↓
ACCEPT / NEGOTIATE / REJECT
```

## Inputs

- Product / SKU
- Requested quantity
- Buyer budget
- Deadline
- Price flexibility
- Quantity flexibility
- Timing flexibility
- Substitution tolerance

## Live baseline rule

For a fresh request, the baseline is feasible only when **both** conditions hold:

1. locked merchant availability can support the requested quantity by the deadline; and
2. the requested transaction total fits the buyer's budget ceiling after the selected price-flexibility tolerance.

This prevents the live room from accepting a transaction that is physically possible but economically outside the buyer's stated budget.

The persisted 500-request artifacts are not regenerated or changed by the live room.

## Recommendation rule

- **ACCEPT:** the baseline is feasible and no safe alternative clears MIRROR's strict improvement threshold.
- **NEGOTIATE:** the baseline is infeasible but a safe recovery exists, or a safe alternative materially beats a feasible baseline.
- **REJECT:** no safe transaction survives the locked constraints and P05 downside gate.

The UI shows only **competitive safe alternatives**. When the baseline is already the best choice, weaker safe candidates are not presented as recommendations.

## Output

The room returns:

- final decision
- baseline feasibility
- baseline transaction total and buyer budget ceiling
- number of candidates evaluated
- P05 gate rejections
- safe survivor count
- selected candidate, when one exists
- competitive safe alternatives only
- a short field-backed explanation of why the decision won

## Evidence boundary

The live request is evaluated against the locked merchant/catalog state but is **not appended to the persisted 500-request benchmark**. This keeps benchmark evidence deterministic while still allowing an interactive product demonstration.

The live endpoint also does not create a Razorpay payment order. Payment remains a separate execution boundary.

## Deployment

The live route is registered by `backend.ai_app:app`, which imports the existing deterministic application and adds the live endpoint.

Render Start Command:

```text
uvicorn backend.ai_app:app --host 0.0.0.0 --port $PORT
```

The repository also includes `render.yaml` with this configuration.

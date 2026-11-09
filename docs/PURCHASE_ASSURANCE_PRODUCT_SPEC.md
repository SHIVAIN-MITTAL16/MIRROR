# MIRROR — Purchase Assurance Product Specification

**Status:** Product specification and target acceptance criteria; not an implementation inventory. Check [Current State](CURRENT_STATE.md) and the root README for delivered functionality and blockers.
**Branch:** `mirror-purchase-assurance`  
**Product:** Buyer-first AI Purchase Assurance Agent

## 1. Product definition

MIRROR helps an online buyer preserve and verify the expectations behind a purchase. It converts the buyer's stated requirements and the seller's disclosed offer into a structured Purchase Promise Passport, checks available fulfilment evidence against that passport, and helps the buyer prepare an appropriate next action when a mismatch is detected.

**Product promise:** Your purchase. Your promise. Your AI protection.

**Core line:** Your receipt remembers what you paid. MIRROR remembers what you were promised.

## 2. Primary user and initial scope

- Primary user: an individual online buyer.
- Initial product category: consumer electronics, starting with laptops.
- Initial demo environment: a controlled MIRROR storefront/catalogue and PayPal Sandbox.
- The first release is not a universal browser extension and does not claim access to arbitrary merchant order systems.
- Fulfilment events that cannot be obtained from a real integration must be clearly labelled as simulated demo events.

## 3. Core user journey

1. Buyer describes the product and purchase conditions in natural language.
2. AI extracts candidate conditions into structured fields.
3. Buyer reviews and confirms the conditions.
4. MIRROR evaluates a participating/demo seller offer against the confirmed conditions and records the source/evidence for each field.
5. Buyer proceeds through PayPal Sandbox checkout.
6. MIRROR associates the PayPal order/transaction reference with the passport.
7. Fulfilment updates are received from an explicitly connected source or injected as labelled demo events.
8. MIRROR compares observed facts with the confirmed promise.
9. If a mismatch is found, MIRROR explains it, shows evidence and recommends a next action.
10. Buyer explicitly approves any consequential action. MIRROR never silently changes an order, submits a dispute, or initiates a refund.

## 4. Purchase Promise Passport

The Passport is the central product object. It is structured data, not merely an LLM conversation transcript.

### Required fields

- `passport_id`: unique internal identifier.
- `buyer_id`: internal buyer identifier; minimise personal data.
- `status`: lifecycle state.
- `created_at`, `updated_at`: timestamps.
- `buyer_intent`: original natural-language request.
- `confirmed_conditions`: buyer-approved constraints.
- `offer_snapshot`: product, seller, price, shipping, taxes/fees when disclosed, return terms and delivery promise.
- `evidence_items`: source, captured value, timestamp, source type and integrity metadata.
- `paypal_order_id`: nullable until a PayPal Sandbox order is created.
- `fulfilment_events`: observed or explicitly simulated events.
- `mismatches`: detected differences between promise and observed facts.
- `recommended_actions`: explanation and permitted next steps.
- `buyer_approvals`: records of explicit buyer approval for consequential actions.

### Condition structure

Each condition should contain:
- `condition_id`
- `type` (e.g. max_total_price, minimum_ram_gb, minimum_storage_gb, delivery_deadline, return_window)
- `operator`
- `value`
- `unit` where applicable
- `hard_or_soft`
- `buyer_confirmed`
- `evidence_status` (verified, seller-stated, inferred, missing, conflicting)
- `source_reference`

Do not treat AI-extracted conditions as authoritative until the buyer confirms them.

## 5. Lifecycle states

Initial proposed states:

- `DRAFT`: intent is being captured.
- `AWAITING_BUYER_CONFIRMATION`: AI has extracted conditions; buyer must review.
- `READY_FOR_CHECKOUT`: offer has passed the available checks.
- `PAYMENT_PENDING`: PayPal order exists but payment is not complete.
- `PURCHASED`: PayPal reports the relevant payment/order state as completed.
- `FULFILMENT_MONITORING`: awaiting fulfilment evidence.
- `ATTENTION_REQUIRED`: a mismatch or material uncertainty needs buyer attention.
- `RESOLUTION_PREPARED`: evidence and suggested action are ready for review.
- `RESOLVED`: buyer confirms the issue is resolved.
- `CANCELLED`: purchase or passport cancelled.
- `CLOSED`: monitoring ended.

A state transition must be driven by a recorded event and validated by backend logic, not by an LLM response alone.

## 6. AI responsibilities and safety boundaries

AI may:
- Extract buyer intent into candidate structured conditions.
- Interpret product descriptions and seller-stated policies.
- Identify ambiguity, missing evidence and contradictions.
- Summarise fulfilment events and explain mismatches.
- Recommend and draft buyer communications or resolution steps.
- Select from a limited, explicitly permitted set of tools.

Deterministic code must:
- Validate schema, ranges, currency and totals.
- Enforce buyer-confirmed hard constraints.
- Verify payment state from trusted PayPal server-side responses/webhooks.
- Validate lifecycle transitions and permissions.
- Require explicit buyer approval for payment, order changes, cancellation, refund or dispute-related submission.

AI must never invent evidence, claim that a seller promise is verified when it is only seller-stated, guarantee refunds, or submit consequential actions without approval.

## 7. Initial mismatch types

- `PRICE_CHANGED`: final disclosed total exceeds the buyer-confirmed ceiling.
- `SPECIFICATION_MISMATCH`: product attributes conflict with confirmed requirements.
- `DELIVERY_DELAY`: observed delivery estimate/event exceeds the confirmed deadline.
- `RETURN_TERMS_CONFLICT`: disclosed return terms conflict with the buyer's requirement.
- `MISSING_EVIDENCE`: a material condition cannot currently be verified.
- `CONTRADICTORY_EVIDENCE`: two sources provide conflicting facts.

A missing field is not proof of a breach. It should be shown as unknown and may require buyer attention.

## 8. MVP acceptance criteria

The first working demo is complete when:

1. A buyer can enter a natural-language laptop request.
2. AI extracts structured conditions and the buyer can edit/confirm them.
3. A catalogue offer can be evaluated against those conditions.
4. MIRROR creates and displays a Passport with evidence status per condition.
5. A PayPal Sandbox order can be created and completed in a controlled checkout.
6. The PayPal order reference is associated with the Passport.
7. A clearly labelled demo fulfilment event can be added.
8. MIRROR detects at least one deliberate mismatch and explains which confirmed condition it violates.
9. MIRROR prepares a resolution recommendation with supporting evidence.
10. The buyer must approve any consequential action.
11. The UI distinguishes real PayPal Sandbox events from simulated fulfilment events.

## 9. Reuse from the existing MIRROR system

Preserve and reuse where technically appropriate:
- Existing FastAPI application and deployment.
- Existing visual design system and dashboard components.
- Existing explainability patterns and decision-pipeline visualisation.
- Existing risk-model code only if it has a justified role in buyer-facing fulfilment risk and can be validated for that purpose.

Do not carry over merchant-margin optimisation, merchant profit scoring or synthetic benchmark statistics as if they were buyer purchase assurance. These belong to the previous product direction and must be isolated or retired from the new buyer-facing experience.

## 10. Explicit non-goals for the hackathon MVP

- Universal monitoring of every online merchant.
- Automatic refunds, chargebacks or disputes.
- Claims of guaranteed buyer protection.
- Production integrations with merchants whose APIs/permissions are unavailable.
- Training a new ML model without appropriate real or defensible labelled data.
- Adding sponsor tools that do not materially support the user journey.

## 11. Open implementation decisions for Phase 2

- Persistence layer and migration strategy.
- AI provider/model and structured-output contract.
- Product catalogue source and Channel3 access.
- PayPal Sandbox integration and webhook verification.
- Fulfilment event source versus labelled simulation.
- Evidence storage and retention policy.

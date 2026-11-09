# MIRROR - Current State Ledger

**Last audited:** 9 November 2026
**Branch:** `mirror-purchase-assurance`

This file describes the checked local working tree. It is not a deployment or live-provider certification.

## Implemented in the repository

- Buyer-intent extraction through Gemini structured output, followed by strict server-side validation and explicit buyer confirmation.
- Empty, clearly labelled fallback for missing Gemini configuration and transient network/timeouts. It never invents proposals.
- SQLite Purchase Passports, buyer/merchant condition ownership, evidence provenance, append-only audit tables, and deterministic condition-level evaluation.
- Seller offer submission and evidence association. Seller-declared uploads remain raw/unverified; no evidence verifier exists.
- PayPal sandbox Orders API routes, official JavaScript SDK integration, APPROVE gating, server-side amount/currency validation, persisted lifecycle fields, idempotency, and PayPal signature verification for webhook reconciliation.
- Channel3 search/product-detail adapter. Live access depends on `CHANNEL3_API_KEY`.
- Product comparison using AG Grid Community loaded from a pinned CDN, with a semantic table fallback if that import fails.
- Buyer issue-report creation and retrieval. Reports remain `open`; there is no authenticated resolver or resolution-state transition API.
- Render Blueprint, local launcher, `.env.example`, and importable Postman collection/environment.
- The old deterministic merchant/inventory and ML experiment remains available as an explicitly experimental surface; it is not the buyer product or payment workflow.

## Verification performed

- Backend unittest suite: 94 tests passed in the local suite; provider and payment interactions are mocked.
- Frontend JavaScript syntax, Python compilation, local asset references, Postman JSON parsing, and `git diff --check` passed in the audit run.
- No browser workflow, live Gemini request, Channel3 request, PayPal sandbox order/capture, webhook delivery, or Render deployment was verified.

## Credentials and blockers

- A nonempty `GEMINI_API_KEY` is present in the ignored local `.env`; its value is deliberately not recorded here.
- PayPal sandbox client ID, client secret, webhook ID, and Channel3 API key were not configured in the local `.env` or process environment at audit time.
- Buyer and seller identity, Passport ownership, and report ownership are unauthenticated. Rate limiting is not implemented.
- No independent evidence verification source exists. Unverified or simulated evidence cannot pass conditions, so the current demo safely escalates and blocks checkout.
- Shipping, taxes, fulfilment monitoring, refunds, PayPal dispute filing, and dispute adjudication are not implemented.
- Render configuration exists, but services, secrets, webhook registration, CORS origin, and public URLs still require account setup and deployment verification.

## Readiness

**Controlled prototype.** It is not production-ready or a complete sandbox payment demonstration. See the repository README for current launch instructions and the exact limitations.

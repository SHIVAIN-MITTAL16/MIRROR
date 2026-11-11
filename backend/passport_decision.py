"""Deterministic two-sided evaluation of Passport conditions and linked evidence."""

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel


OUTCOMES = ("APPROVE", "NEGOTIATE", "REJECT", "ESCALATE")
NUMERIC_TYPES = {"price", "quantity", "delivery_days", "ram", "storage_capacity"}
TEXT_TYPES = {
    "product_name", "seller_name", "currency", "return_terms", "item_condition", "sku_id",
    "brand", "model", "processor_family", "display_resolution", "operating_system",
}
CONDITION_TYPES = NUMERIC_TYPES | TEXT_TYPES
NUMERIC_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte"}
TEXT_OPERATORS = {"eq", "ne"}


class ConditionDecision(BaseModel):
    condition_id: str | None
    owner: Literal["buyer", "merchant"]
    condition_type: str | None
    operator: str | None
    expected_value: str | None
    observed_values: list[str]
    hard_or_soft: Literal["hard", "soft"] | None
    status: Literal["passed", "failed", "unresolved"]
    evidence_ids: list[str]
    evidence_statuses: list[str]
    simulated_evidence_ids: list[str]
    confirmation_required: str | None
    confirmation_received: bool
    reasons: list[str]


class PassportDecision(BaseModel):
    passport_id: str
    outcome: Literal["APPROVE", "NEGOTIATE", "REJECT", "ESCALATE"]
    passed_conditions: list[ConditionDecision]
    failed_conditions: list[ConditionDecision]
    unresolved_conditions: list[ConditionDecision]
    reasons: list[str]
    ml_assessment: dict[str, Any] | None = None


def _canonical(value: str, condition_type: str) -> str | Decimal:
    if condition_type in NUMERIC_TYPES:
        try:
            number = Decimal(value.strip())
        except (InvalidOperation, AttributeError):
            raise ValueError("value is not a valid number")
        if not number.is_finite():
            raise ValueError("value must be finite")
        return number
    return value.strip().casefold()


def _compare(condition: dict, observed: str) -> bool:
    condition_type = condition["condition_type"]
    operator = condition["operator"]
    if condition_type not in CONDITION_TYPES:
        raise ValueError("unsupported condition type")
    allowed = NUMERIC_OPERATORS if condition_type in NUMERIC_TYPES else TEXT_OPERATORS
    if operator not in allowed:
        raise ValueError("unsupported operator for condition type")
    expected = _canonical(condition["expected_value"], condition_type)
    actual = _canonical(observed, condition_type)
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "gt":
        return actual > expected
    return actual >= expected


def _evaluate_condition(condition: dict, evidence: list[dict]) -> ConditionDecision:
    owner = condition.get("owner", "buyer")
    reasons: list[str] = []
    confirmation_field = "buyer_confirmed" if owner == "buyer" else "merchant_confirmed"
    if not condition.get(confirmation_field, False):
        reasons.append(f"{owner}_confirmation_missing")
    condition_type = condition.get("condition_type")
    if condition_type not in CONDITION_TYPES:
        reasons.append("unsupported_condition_type")
    else:
        allowed_operators = NUMERIC_OPERATORS if condition_type in NUMERIC_TYPES else TEXT_OPERATORS
        if condition.get("operator") not in allowed_operators:
            reasons.append("unsupported_operator")

    evidence_ids = list(dict.fromkeys(item["id"] for item in evidence))
    observed_values: list[str] = []
    if not evidence:
        reasons.append("evidence_missing_or_unlinked")
    else:
        fresh_catalogue_claims = [
            claim
            for item in evidence
            if item.get("evidence_type") == "channel3_product_catalogue"
            and item.get("source_classification") == "server_source"
            and not item.get("is_simulated")
            and not item.get("evidence_stale")
            and item.get("verification_status") == "verified"
            and item.get("lifecycle_state") == "verified"
            for claim in item.get("claims", [])
            if claim.get("claim_type") == condition_type
            and claim.get("verification_event_state") == "verified"
        ]
        independent_claim_supports_type = any(
            item.get("source_classification") == "server_source"
            and not item.get("is_simulated")
            and not item.get("evidence_stale")
            and item.get("verification_status") == "verified"
            and item.get("lifecycle_state") == "verified"
            and any(
                claim.get("claim_type") == condition_type
                and claim.get("verification_event_state") == "verified"
                for claim in item.get("claims", [])
            )
            for item in evidence
        )
        for item in evidence:
            if item.get("evidence_stale") and item.get("evidence_type") == "channel3_product_catalogue":
                stale_claims = [
                    claim for claim in item.get("claims", [])
                    if claim.get("claim_type") == condition_type
                    and claim.get("verification_event_state") == "verified"
                ]
                if fresh_catalogue_claims:
                    if all(any(
                        stale.get("claim_value") == fresh.get("claim_value")
                        and str(stale.get("unit") or "").casefold() == str(fresh.get("unit") or "").casefold()
                        for fresh in fresh_catalogue_claims
                    ) for stale in stale_claims):
                        continue
                    observed_values.extend(claim.get("claim_value", "") for claim in stale_claims)
                    reasons.append("conflicting_verified_evidence")
                    continue
                reasons.append("evidence_stale")
                continue
            # Seller text is always retained and displayed as a declaration.
            # A seller declaration stays visible, but does not act as additional
            # proof when an independent server source has an exact scoped claim.
            # Conflicts create no matching claim and therefore remain unresolved.
            if (
                independent_claim_supports_type
                and item.get("evidence_type") == "seller_offer_text"
                and item.get("source_classification") == "client_submitted"
            ):
                continue
            if item.get("is_simulated"):
                reasons.append("simulated_evidence")
            if item.get("evidence_stale"):
                reasons.append("evidence_stale")
            claims = item.get("claims")
            if claims is None:
                # Keep the pure evaluator's earlier input shape useful to
                # callers while persisted evaluation supplies grouped claims.
                claims = ([{
                    "claim_id": item.get("claim_id"),
                    "claim_type": item.get("claim_type"),
                    "claim_value": item.get("claim_value", ""),
                    "unit": item.get("claim_unit"),
                    "verification_event_state": item.get("verification_event_state"),
                }] if item.get("claim_id") else [])
            if not claims:
                reasons.append("evidence_missing_or_unlinked")
            if (
                item.get("verification_status") != "verified"
                or item.get("lifecycle_state") != "verified"
            ):
                reasons.append("evidence_not_verified")
            for claim in claims:
                if claim.get("claim_type") != condition_type:
                    reasons.append("evidence_scope_mismatch")
                if condition.get("unit") is not None and str(claim.get("unit") or "").casefold() != str(condition.get("unit")).casefold():
                    reasons.append("evidence_scope_mismatch")
                if claim.get("verification_event_state") != "verified":
                    reasons.append("evidence_not_verified")
                observed_values.append(claim.get("claim_value", ""))

    # Even a matching verified item cannot mask a second unverified or simulated
    # item attached to the same condition.
    if reasons:
        return ConditionDecision(
            condition_id=condition["id"], owner=owner,
            condition_type=condition["condition_type"], hard_or_soft=condition["hard_or_soft"],
            operator=condition["operator"], expected_value=condition["expected_value"],
            observed_values=observed_values,
            evidence_statuses=[str(item.get("verification_status", "unknown")) for item in evidence],
            simulated_evidence_ids=[item["id"] for item in evidence if item.get("is_simulated")],
            confirmation_required=confirmation_field,
            confirmation_received=bool(condition.get(confirmation_field, False)),
            status="unresolved", evidence_ids=evidence_ids, reasons=sorted(set(reasons)),
        )

    try:
        canonical_values = {
            _canonical(value, condition["condition_type"])
            for value in observed_values
        }
        if len(canonical_values) != 1:
            reasons.append("conflicting_verified_evidence")
            status = "unresolved"
        else:
            passes = _compare(condition, observed_values[0])
            status = "passed" if passes else "failed"
            if passes:
                reasons.append("verified_evidence_satisfies_condition")
            else:
                reasons.append("verified_value_does_not_satisfy_condition")
    except ValueError as error:
        status = "unresolved"
        reasons.append(str(error))

    return ConditionDecision(
        condition_id=condition["id"], owner=owner,
        condition_type=condition["condition_type"], hard_or_soft=condition["hard_or_soft"],
        operator=condition["operator"], expected_value=condition["expected_value"],
        observed_values=observed_values,
        evidence_statuses=[str(item.get("verification_status", "unknown")) for item in evidence],
        simulated_evidence_ids=[item["id"] for item in evidence if item.get("is_simulated")],
        confirmation_required=confirmation_field,
        confirmation_received=bool(condition.get(confirmation_field, False)),
        status=status, evidence_ids=evidence_ids, reasons=reasons,
    )


def evaluate_conditions(passport_id: str, conditions: list[dict], evidence_by_condition: dict[str, list[dict]]) -> PassportDecision:
    """Evaluate every condition independently, then apply the documented precedence."""
    assessed = [
        _evaluate_condition(condition, evidence_by_condition.get(condition["id"], []))
        for condition in conditions
    ]
    for owner in ("buyer", "merchant"):
        if not any(item.owner == owner for item in assessed):
            assessed.append(ConditionDecision(
                condition_id=None, owner=owner, condition_type=None, hard_or_soft=None,
                operator=None, expected_value=None, observed_values=[], evidence_statuses=[],
                simulated_evidence_ids=[],
                confirmation_required=None, confirmation_received=False,
                status="unresolved", evidence_ids=[], reasons=["party_conditions_missing"],
            ))

    passed = [item for item in assessed if item.status == "passed"]
    failed = [item for item in assessed if item.status == "failed"]
    unresolved = [item for item in assessed if item.status == "unresolved"]

    if any(item.hard_or_soft == "hard" for item in failed):
        outcome = "REJECT"
        reasons = ["A verified hard condition failed."]
    elif unresolved:
        outcome = "ESCALATE"
        reasons = ["Required confirmation or trustworthy, unambiguous evidence is unresolved."]
    elif failed:
        outcome = "NEGOTIATE"
        reasons = ["One or more verified soft conditions failed."]
    else:
        outcome = "APPROVE"
        reasons = ["Both parties have confirmed conditions and every condition passed verified evidence."]

    return PassportDecision(
        passport_id=passport_id,
        outcome=outcome,
        passed_conditions=passed,
        failed_conditions=failed,
        unresolved_conditions=unresolved,
        reasons=reasons,
    )


def _ml_features(conditions: list[dict], assessed: PassportDecision) -> tuple[str, int, int] | None:
    """Return exact structured inputs only when unique, confirmed conditions passed."""
    if assessed.outcome != "APPROVE":
        return None
    by_type: dict[str, set[str]] = {"sku_id": set(), "quantity": set(), "delivery_days": set()}
    condition_status = {item.condition_id: item.status for item in assessed.passed_conditions}
    for condition in conditions:
        kind = condition["condition_type"]
        if kind in by_type:
            if condition_status.get(condition["id"]) != "passed":
                return None
            by_type[kind].add(condition["expected_value"].strip())
    if any(len(values) != 1 for values in by_type.values()):
        return None
    try:
        quantity = int(next(iter(by_type["quantity"])))
        delivery_days = int(next(iter(by_type["delivery_days"])))
    except (ValueError, StopIteration):
        return None
    sku_id = next(iter(by_type["sku_id"]))
    if quantity <= 0 or delivery_days < 0 or not sku_id:
        return None
    return sku_id, quantity, delivery_days


def apply_fulfilment_risk(decision: PassportDecision, conditions: list[dict]) -> PassportDecision:
    """Use the existing SLA model only with explicit SKU, quantity and day conditions."""
    features = _ml_features(conditions, decision)
    if features is None:
        reason = (
            "Deterministic conditions are not approvable; ML cannot override them."
            if decision.outcome != "APPROVE"
            else "Required confirmed, verified SKU, quantity and delivery_days conditions are unavailable."
        )
        decision.ml_assessment = {"applied": False, "reason": reason}
        return decision

    sku_id, quantity, days = features
    from backend.main import load_locked_data
    from backend.risk_model import get_risk_model, risk_features_for_request

    states = load_locked_data()["merchant_states_by_sku"]
    state = states.get(sku_id)
    if state is None:
        decision.ml_assessment = {"applied": False, "reason": "The explicitly stated SKU has no matching risk-model state."}
        return decision

    model = get_risk_model()
    model_features = risk_features_for_request(state, quantity, days)
    probability = model.predict_probability(model_features)
    decision.ml_assessment = {
        "applied": True,
        "model_version": model.version,
        "threshold": model.threshold,
        "sla_miss_probability": round(probability, 6),
        "evidence_status": "SYNTHETIC_MODEL_ESTIMATE_NOT_EVIDENCE",
    }
    if probability >= model.threshold:
        decision.outcome = "ESCALATE"
        decision.reasons.append("The existing fulfilment risk model exceeded its threshold; verified evidence remains unchanged.")
    return decision

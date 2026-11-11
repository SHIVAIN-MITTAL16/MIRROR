"""Narrow Channel3-backed verification for catalogue product facts.

Channel3 catalogue facts describe its product record. They do not establish
that a seller owns, authenticates, ships, or delivers the physical item.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.passports import connect, utc_now, require_buyer_passport
from backend.auth import require_authenticated
from backend.product_discovery import _channel3_request

router = APIRouter(prefix="/api/passports", tags=["Passport catalogue verification"])
VERIFIER_IDENTITY = "MIRROR Channel3 catalogue adapter"
VERIFIER_VERSION = "1"
MAX_SOURCE_AGE = timedelta(days=30)
ALLOWED_CAPACITY_UNITS = {"GB", "GIB", "TB", "TIB"}

TEXT_ATTRIBUTES = {
    "brand": "brands",
    "model": "model",
    "processor_family": "processor-family",
    "display_resolution": "display-resolution",
    "operating_system": "operating-system",
}
NUMERIC_ATTRIBUTES = {"ram": "ram", "storage_capacity": "storage-capacity"}
SUPPORTED_CATALOGUE_CONDITION_TYPES = set(TEXT_ATTRIBUTES) | set(NUMERIC_ATTRIBUTES) | {"product_name"}


class CatalogueVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=160)
    refresh: bool = False


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _freshness_issue(product: dict, now: datetime) -> str | None:
    source_time = product.get("updated_at") or product.get("last_updated_at")
    if source_time is None:
        # Current Channel3 Product responses omit a source-update timestamp.
        # The server records when it retrieved the response, but does not claim
        # that this proves when the provider last refreshed the catalogue row.
        return None
    if not isinstance(source_time, str):
        return "invalid_source_timestamp"
    try:
        updated = _utc_datetime(source_time)
    except (TypeError, ValueError):
        return "invalid_source_timestamp"
    if updated > now + timedelta(minutes=5):
        return "future_source_timestamp"
    if now - updated > MAX_SOURCE_AGE:
        return "stale_source_data"
    return None


def _one_text(value: object) -> tuple[str | None, str | None]:
    if isinstance(value, str):
        text = value.strip()
        return (text, None) if text else (None, "missing_attribute")
    if isinstance(value, list):
        values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        unique = {item.casefold(): item for item in values}
        if len(unique) == 1:
            return next(iter(unique.values())), None
        return None, "missing_attribute" if not unique else "ambiguous_attribute"
    return None, "missing_or_unsupported_attribute_shape"


def _product_fact(product: dict, condition_type: str) -> tuple[dict | None, str | None]:
    attributes = product.get("structured_attributes")
    attributes = attributes if isinstance(attributes, dict) else {}
    if condition_type == "product_name":
        value, issue = _one_text(product.get("title"))
        return ({"type": condition_type, "value": value, "unit": None}, None) if value else (None, issue)
    if condition_type == "brand":
        value, issue = _one_text(product.get("brands", product.get("brand")))
        return ({"type": condition_type, "value": value, "unit": None}, None) if value else (None, issue)
    if condition_type == "model":
        value, issue = _one_text(attributes.get("model", product.get("model")))
        return ({"type": condition_type, "value": value, "unit": None}, None) if value else (None, issue)
    attribute_name = TEXT_ATTRIBUTES.get(condition_type)
    if attribute_name:
        value, issue = _one_text(attributes.get(attribute_name))
        return ({"type": condition_type, "value": value, "unit": None}, None) if value else (None, issue)
    if condition_type in NUMERIC_ATTRIBUTES:
        raw_value, issue = _one_text(attributes.get(NUMERIC_ATTRIBUTES[condition_type]))
        if not raw_value:
            return None, issue
        match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(GB|GIB|TB|TIB)\s*", raw_value, re.IGNORECASE)
        if not match:
            return None, "unsupported_value_or_unit"
        unit_code = match.group(2).upper()
        unit = {"GIB": "GiB", "TIB": "TiB"}.get(unit_code, unit_code)
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:
            return None, "invalid_numeric_attribute"
        if not value.is_finite() or value < 0:
            return None, "invalid_numeric_attribute"
        return {"type": condition_type, "value": str(value), "unit": unit}, None
    return None, "unsupported_claim_type"


def _seller_value_matches(condition_type: str, seller_value: str, fact: dict) -> tuple[bool, str | None]:
    if condition_type in NUMERIC_ATTRIBUTES:
        match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(GB|GIB|TB|TIB)\s*", seller_value, re.IGNORECASE)
        if not match:
            return False, "seller_value_missing_or_unparseable"
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:
            return False, "seller_value_missing_or_unparseable"
        if not value.is_finite():
            return False, "seller_value_missing_or_unparseable"
        return value == Decimal(fact["value"]) and match.group(2).upper() == fact["unit"], "seller_catalogue_conflict"
    return " ".join(seller_value.casefold().split()) == " ".join(str(fact["value"]).casefold().split()), "seller_catalogue_conflict"


def _existing_result(db, evidence_id: str, duplicate: bool) -> dict:
    row = db.execute("""
        SELECT lifecycle_state,verification_status,content_sha256,captured_at
        FROM evidence_items WHERE id=?
    """, (evidence_id,)).fetchone()
    try:
        captured = _utc_datetime(row["captured_at"])
        stale = datetime.now(timezone.utc) - captured > MAX_SOURCE_AGE
    except (TypeError, ValueError):
        stale = True
    claims = [dict(item) for item in db.execute("""
        SELECT claim_type,claim_value,unit FROM evidence_claims WHERE evidence_id=? ORDER BY rowid
    """, (evidence_id,)).fetchall()]
    linked_conditions = [dict(item) for item in db.execute("""
        SELECT c.id AS condition_id,c.condition_type,c.owner,
               claim.claim_id,claim.claim_type,claim.claim_value,claim.unit
        FROM condition_evidence ce JOIN purchase_conditions c ON c.id=ce.condition_id
        LEFT JOIN evidence_claims claim ON claim.claim_id=ce.claim_id AND claim.evidence_id=ce.evidence_id
        WHERE ce.evidence_id=? ORDER BY c.rowid
    """, (evidence_id,)).fetchall()]
    condition_results = []
    for condition in linked_conditions:
        matching = (
            {key: condition[key] for key in ("claim_type", "claim_value", "unit")}
            if condition["claim_id"] and condition["claim_type"] == condition["condition_type"]
            else None
        )
        condition_results.append({
            "condition_id": condition["condition_id"],
            "condition_type": condition["condition_type"],
            "status": "stale" if stale else "verified" if matching else "unsupported",
            **({"claim": matching} if matching else {"reason": "unsupported_claim_type_or_attribute"}),
        })
    return {
        "status": "duplicate" if duplicate else "recorded",
        "evidence_id": evidence_id,
        "lifecycle_state": row["lifecycle_state"],
        "verification_status": row["verification_status"],
        "assurance_category": "stale_catalogue_fact" if stale else (
            "independently_verified_catalogue_fact" if claims else "unsupported_claim"
        ),
        "claims": claims,
        "condition_results": condition_results,
        "duplicate": duplicate,
        "limitations": [
            "A catalogue record does not prove that the seller controls or will deliver the listed item.",
            "Catalogue data does not establish product authenticity, warranty, physical condition, delivery, returns, or seller reliability.",
        ],
    }


def _catalogue_evidence_stale(db, evidence_id: str) -> bool:
    row = db.execute("SELECT captured_at FROM evidence_items WHERE id=?", (evidence_id,)).fetchone()
    try:
        return datetime.now(timezone.utc) - _utc_datetime(row["captured_at"]) > MAX_SOURCE_AGE
    except (TypeError, ValueError):
        return True


@router.post("/{passport_id}/offers/{offer_id}/catalogue-verification", dependencies=[Depends(require_authenticated)])
def verify_offer_catalogue_facts(passport_id: str, offer_id: str, payload: CatalogueVerificationRequest, request: Request):
    """Capture Channel3 facts and audit only exact, unambiguous supported claims."""
    with connect() as db:
        require_buyer_passport(db, passport_id, request.state.user)
        offer = db.execute("""
            SELECT id,product_name FROM offer_snapshots WHERE id=? AND passport_id=?
        """, (offer_id, passport_id)).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="Seller offer not found")
        existing = db.execute("""
            SELECT id FROM evidence_items
            WHERE passport_id=? AND offer_snapshot_id=? AND evidence_type='channel3_product_catalogue'
              AND source_reference=? ORDER BY captured_at DESC,rowid DESC LIMIT 1
        """, (passport_id, offer_id, payload.product_id)).fetchone()
        if existing is not None and (not payload.refresh or not _catalogue_evidence_stale(db, existing["id"])):
            return _existing_result(db, existing["id"], True)

    try:
        response = _channel3_request(f"/v1/products/{quote(payload.product_id, safe='')}", "GET")
    except HTTPException:
        # Existing Channel3 adapter responses contain no credentials or bodies.
        raise
    product = response.get("product", response)
    if not isinstance(product, dict) or product.get("id") != payload.product_id:
        raise HTTPException(status_code=502, detail="Channel3 returned a product record that did not match the requested identifier")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    stale_reason = _freshness_issue(product, now)
    title, title_issue = _one_text(product.get("title"))
    identity_matches = bool(title and title.casefold().strip() == offer["product_name"].casefold().strip())
    identity_issue = None if identity_matches else (title_issue or "catalogue_title_does_not_match_seller_offer")
    snapshot = json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    evidence_id = str(uuid4())
    ingestion_event_id = str(uuid4())
    verification_event_id = str(uuid4())
    result_rows: list[dict] = []
    claims_by_condition: dict[str, dict] = {}
    issues: list[str] = []

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        offer = db.execute("""
            SELECT id,product_name FROM offer_snapshots WHERE id=? AND passport_id=?
        """, (offer_id, passport_id)).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="Seller offer not found")
        existing = db.execute("""
            SELECT id FROM evidence_items
            WHERE passport_id=? AND offer_snapshot_id=? AND evidence_type='channel3_product_catalogue'
              AND source_reference=? ORDER BY captured_at DESC,rowid DESC LIMIT 1
        """, (passport_id, offer_id, payload.product_id)).fetchone()
        if existing is not None and (not payload.refresh or not _catalogue_evidence_stale(db, existing["id"])):
            return _existing_result(db, existing["id"], True)

        buyers = db.execute("""
            SELECT * FROM purchase_conditions WHERE passport_id=? AND owner='buyer' ORDER BY rowid
        """, (passport_id,)).fetchall()
        if not buyers or any(not item["buyer_confirmed"] for item in buyers):
            raise HTTPException(status_code=409, detail="Catalogue verification requires buyer-confirmed Passport conditions")
        sellers = {item["buyer_condition_id"]: item for item in db.execute("""
            SELECT * FROM purchase_conditions WHERE passport_id=? AND owner='merchant' AND offer_snapshot_id=?
        """, (passport_id, offer_id)).fetchall()}
        if set(sellers) != {item["id"] for item in buyers}:
            raise HTTPException(status_code=409, detail="Seller offer conditions do not map exactly to buyer conditions")

        for buyer in buyers:
            kind = buyer["condition_type"]
            reason = None
            fact = None
            if not identity_matches:
                reason = identity_issue or "catalogue_title_does_not_match_seller_offer"
            elif stale_reason:
                reason = stale_reason
            elif kind not in SUPPORTED_CATALOGUE_CONDITION_TYPES:
                reason = "unsupported_claim_type"
            else:
                fact, reason = _product_fact(product, kind)
                if fact is not None and buyer["unit"] is not None and str(fact["unit"]).casefold() != buyer["unit"].casefold():
                    fact = None
                    reason = "catalogue_unit_mismatch_no_conversion_performed"
            if fact is not None:
                merchant = sellers[buyer["id"]]
                if not merchant["merchant_confirmed"]:
                    fact = None
                    reason = "seller_condition_not_confirmed"
            if fact is not None:
                merchant = sellers[buyer["id"]]
                seller_evidence = db.execute("""
                    SELECT captured_value FROM evidence_items
                    WHERE passport_id=? AND offer_snapshot_id=? AND evidence_type='seller_offer_text'
                      AND source_classification='client_submitted' AND id IN (
                        SELECT evidence_id FROM condition_evidence WHERE condition_id=?
                      ) ORDER BY rowid
                """, (passport_id, offer_id, merchant["id"])).fetchall()
                if len(seller_evidence) != 1:
                    fact = None
                    reason = "seller_declaration_missing_or_ambiguous"
                else:
                    matches, conflict_reason = _seller_value_matches(kind, seller_evidence[0]["captured_value"], fact)
                    if not matches:
                        fact = None
                        reason = conflict_reason
            if fact is not None:
                claims_by_condition[buyer["id"]] = fact
                result_rows.append({"condition_id": buyer["id"], "condition_type": kind, "status": "verified", "claim": fact})
            else:
                issues.append(f"{kind}:{reason or 'unsupported_claim'}")
                result_rows.append({"condition_id": buyer["id"], "condition_type": kind,
                                    "status": "conflicting" if reason and "conflict" in reason else "unsupported",
                                    "reason": reason or "unsupported_claim"})

        # A catalogue ID/title mismatch is retained for audit, but never linked
        # as evidence for this seller's conditions.
        link_conditions = [] if not identity_matches else [
            condition_id for buyer in buyers
            for condition_id in (buyer["id"], sellers[buyer["id"]]["id"])
        ]
        target_state = "verified" if claims_by_condition else "unverified"
        description = (
            "Server-retrieved Channel3 product detail snapshot. The snapshot proves only the explicit scoped catalogue facts recorded in its audit event. "
            "It does not prove the seller controls, authenticates, or will fulfil the offer."
        )
        db.execute("""
            INSERT INTO evidence_items
            (id,passport_id,evidence_type,source_name,source_reference,captured_value,
             verification_status,captured_at,is_simulated,original_content,content_type,
             received_at,source_classification,content_sha256,description,offer_snapshot_id,lifecycle_state)
            VALUES(?,?,'channel3_product_catalogue','Channel3',?,?, 'unverified',?,0,?,
                   'application/json',?,'server_source',?,?,?,'raw')
        """, (evidence_id, passport_id, payload.product_id, title or "Channel3 product record",
              now_iso, snapshot, now_iso, digest, description, offer_id))
        db.execute("""
            INSERT INTO evidence_verification_events
            (event_id,evidence_id,from_state,to_state,actor_type,actor_reference,method,
             recorded_at,proves_json,does_not_prove_json,reason)
            VALUES(?,?,NULL,'raw','system',?,'channel3_product_detail_capture',?,'[]',?,?)
        """, (ingestion_event_id, evidence_id, offer_id, now_iso,
              json.dumps(["Physical item identity, seller fulfilment, warranty, condition, delivery, and return compliance are not proven."]),
              "Captured Channel3 product detail response and its server retrieval timestamp."))
        proves = list({json.dumps(item, sort_keys=True): item for item in claims_by_condition.values()}.values())
        does_not_prove = [
            f"{item['condition_type']}: {item['reason']}"
            for item in result_rows if item["status"] != "verified"
        ] + [
            "Seller identity, seller control of the item, physical authenticity, fulfilment, warranty, physical condition, delivery and return-policy compliance."
        ]
        if product.get("updated_at") is None and product.get("last_updated_at") is None:
            does_not_prove.append("Channel3 supplied no source-update timestamp; server retrieval time does not prove when its catalogue data was last refreshed.")
        verify_reason = (
            "Channel3 product identity matched the seller offer title; only exact, unambiguous attributes matching the seller declaration were claimed."
            if target_state == "verified" else "No eligible catalogue claim could be established for this snapshot."
        )
        db.execute("""
            INSERT INTO evidence_verification_events
            (event_id,evidence_id,from_state,to_state,actor_type,actor_reference,verifier_identity,
             verifier_version,method,recorded_at,proves_json,does_not_prove_json,reason)
            VALUES(?,?,'raw',?,'server_verifier',?,?,?,?,?,?,?,?)
        """, (verification_event_id, evidence_id, target_state, offer_id, VERIFIER_IDENTITY,
              VERIFIER_VERSION, "channel3_product_specification_match", now_iso,
              json.dumps(proves), json.dumps(does_not_prove), verify_reason))
        db.execute("""
            UPDATE evidence_items SET lifecycle_state=?,verification_status=? WHERE id=?
        """, (target_state, target_state, evidence_id))

        claims_by_type: dict[str, str] = {}
        for condition_id, fact in claims_by_condition.items():
            # One catalogue claim per type/value/unit can support the buyer
            # condition and the corresponding seller commitment.
            key = json.dumps(fact, sort_keys=True)
            claim_id = claims_by_type.get(key)
            if claim_id is None:
                claim_id = str(uuid4())
                claims_by_type[key] = claim_id
                db.execute("""
                    INSERT INTO evidence_claims
                    (claim_id,evidence_id,verification_event_id,claim_type,claim_value,unit,created_at)
                    VALUES(?,?,?,?,?,?,?)
                """, (claim_id, evidence_id, verification_event_id, fact["type"],
                      str(fact["value"]), fact["unit"], now_iso))
            buyer = next(item for item in buyers if item["id"] == condition_id)
            seller = sellers[condition_id]
            for linked_condition in (buyer["id"], seller["id"]):
                db.execute("""
                    INSERT INTO condition_evidence(condition_id,evidence_id,claim_id) VALUES(?,?,?)
                """, (linked_condition, evidence_id, claim_id))
        if identity_matches:
            for item in buyers:
                if item["id"] in claims_by_condition:
                    continue
                for linked_condition in (item["id"], sellers[item["id"]]["id"]):
                    db.execute("""
                        INSERT INTO condition_evidence(condition_id,evidence_id,claim_id) VALUES(?,?,NULL)
                    """, (linked_condition, evidence_id))

    return {
        "status": "verified" if claims_by_condition else ("identity_mismatch" if not identity_matches else "unresolved"),
        "evidence_id": evidence_id,
        "product_id": payload.product_id,
        "source": "Channel3",
        "retrieved_at": now_iso,
        "identity_matches_offer": identity_matches,
        "catalogue_source_timestamp_status": stale_reason or "provider_timestamp_not_supplied",
        "assurance_category": "stale_catalogue_fact" if stale_reason else (
            "independently_verified_catalogue_fact" if claims_by_condition else "unsupported_claim"
        ),
        "condition_results": result_rows,
        "limits": [
            "A catalogue fact does not establish that the seller's physical item is authentic or matches the catalogue record.",
            "Catalogue facts do not prove seller reliability, inventory control, warranty, physical condition, delivery, fulfilment, or return-policy compliance.",
        ],
    }

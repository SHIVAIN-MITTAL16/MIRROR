"""SQLite persistence and API schemas for buyer Purchase Passports."""

import os
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.passport_decision import (
    CONDITION_TYPES, NUMERIC_TYPES, NUMERIC_OPERATORS, TEXT_OPERATORS,
    PassportDecision, apply_fulfilment_risk, evaluate_conditions,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path() -> Path:
    configured = os.getenv("MIRROR_DATABASE_PATH")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "data" / "mirror.sqlite3"


@contextmanager
def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS purchase_passports (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','fulfilled','disputed','cancelled')),
            buyer_intent TEXT NOT NULL CHECK(length(trim(buyer_intent)) > 0),
            currency TEXT NOT NULL CHECK(length(currency) = 3 AND currency = upper(currency)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            paypal_order_id TEXT,
            paypal_status TEXT NOT NULL DEFAULT 'not_started',
            paypal_offer_snapshot_id TEXT,
            paypal_request_id TEXT,
            paypal_capture_request_id TEXT,
            paypal_amount TEXT,
            paypal_currency TEXT,
            paypal_capture_id TEXT
        );
        CREATE TABLE IF NOT EXISTS purchase_conditions (
            id TEXT PRIMARY KEY,
            passport_id TEXT NOT NULL REFERENCES purchase_passports(id) ON DELETE CASCADE,
            condition_type TEXT NOT NULL CHECK(length(trim(condition_type)) > 0),
            operator TEXT NOT NULL CHECK(length(trim(operator)) > 0),
            expected_value TEXT NOT NULL CHECK(length(trim(expected_value)) > 0),
            unit TEXT,
            hard_or_soft TEXT NOT NULL CHECK(hard_or_soft IN ('hard','soft')),
            buyer_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(buyer_confirmed IN (0,1)),
            buyer_confirmed_at TEXT,
            offer_snapshot_id TEXT REFERENCES offer_snapshots(id),
            buyer_condition_id TEXT REFERENCES purchase_conditions(id),
            evidence_status TEXT NOT NULL DEFAULT 'unverified' CHECK(evidence_status IN ('unverified','supported','contradicted','unknown'))
        );
        CREATE TABLE IF NOT EXISTS offer_snapshots (
            id TEXT PRIMARY KEY,
            passport_id TEXT NOT NULL REFERENCES purchase_passports(id) ON DELETE CASCADE,
            product_name TEXT NOT NULL,
            seller_name TEXT NOT NULL,
            product_url TEXT,
            displayed_price REAL NOT NULL CHECK(displayed_price >= 0),
            currency TEXT NOT NULL CHECK(length(currency) = 3 AND currency = upper(currency)),
            delivery_promise TEXT,
            return_terms TEXT,
            captured_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence_items (
            id TEXT PRIMARY KEY,
            passport_id TEXT NOT NULL REFERENCES purchase_passports(id) ON DELETE CASCADE,
            evidence_type TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_reference TEXT,
            captured_value TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)),
            original_content TEXT,
            content_type TEXT,
            received_at TEXT,
            claimed_source_name TEXT,
            claimed_source_reference TEXT,
            claimed_captured_at TEXT,
            source_classification TEXT NOT NULL DEFAULT 'legacy_unknown'
                CHECK(source_classification IN ('client_submitted','server_source','legacy_unknown','simulated')),
            content_sha256 TEXT,
            description TEXT,
            offer_snapshot_id TEXT REFERENCES offer_snapshots(id),
            lifecycle_state TEXT NOT NULL DEFAULT 'unverified'
                CHECK(lifecycle_state IN ('raw','unverified','verified','rejected','simulated','conflicting'))
        );
        CREATE TABLE IF NOT EXISTS fulfilment_events (
            id TEXT PRIMARY KEY,
            passport_id TEXT NOT NULL REFERENCES purchase_passports(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            source_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS buyer_approvals (
            id TEXT PRIMARY KEY,
            passport_id TEXT NOT NULL REFERENCES purchase_passports(id) ON DELETE CASCADE,
            action_type TEXT NOT NULL,
            approval_status TEXT NOT NULL CHECK(approval_status IN ('pending','approved','rejected')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paypal_webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            order_id TEXT,
            received_at TEXT NOT NULL,
            processed_at TEXT,
            processing_status TEXT NOT NULL CHECK(processing_status IN ('received','processed','ignored'))
        );
        CREATE TABLE IF NOT EXISTS passport_disputes (
            id TEXT PRIMARY KEY,
            passport_id TEXT NOT NULL REFERENCES purchase_passports(id),
            condition_id TEXT NOT NULL REFERENCES purchase_conditions(id),
            summary TEXT NOT NULL CHECK(length(trim(summary)) > 0),
            reported_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','under_review','resolved','unable_to_resolve'))
        );
        CREATE TABLE IF NOT EXISTS dispute_evidence (
            dispute_id TEXT NOT NULL REFERENCES passport_disputes(id),
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id),
            PRIMARY KEY(dispute_id,evidence_id)
        );
        CREATE INDEX IF NOT EXISTS idx_conditions_passport ON purchase_conditions(passport_id);
        CREATE INDEX IF NOT EXISTS idx_passports_created ON purchase_passports(created_at);
        CREATE INDEX IF NOT EXISTS idx_evidence_passport ON evidence_items(passport_id);
        CREATE TABLE IF NOT EXISTS evidence_verification_events (
            event_id TEXT PRIMARY KEY,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
            from_state TEXT,
            to_state TEXT NOT NULL CHECK(to_state IN ('raw','unverified','verified','rejected','simulated','conflicting')),
            actor_type TEXT NOT NULL CHECK(actor_type IN ('ingestion_api','server_verifier','migration','system')),
            actor_reference TEXT,
            verifier_identity TEXT,
            verifier_version TEXT,
            method TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            proves_json TEXT NOT NULL DEFAULT '[]',
            does_not_prove_json TEXT NOT NULL DEFAULT '[]',
            reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_events_evidence ON evidence_verification_events(evidence_id, recorded_at);
        CREATE TABLE IF NOT EXISTS evidence_claims (
            claim_id TEXT PRIMARY KEY,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
            verification_event_id TEXT NOT NULL REFERENCES evidence_verification_events(event_id),
            claim_type TEXT NOT NULL CHECK(length(trim(claim_type)) > 0),
            claim_value TEXT NOT NULL,
            unit TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_claims_evidence ON evidence_claims(evidence_id);
        CREATE TABLE IF NOT EXISTS condition_evidence (
            condition_id TEXT NOT NULL REFERENCES purchase_conditions(id) ON DELETE CASCADE,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
            claim_id TEXT REFERENCES evidence_claims(claim_id),
            PRIMARY KEY(condition_id, evidence_id)
        );
        CREATE INDEX IF NOT EXISTS idx_condition_evidence_evidence ON condition_evidence(evidence_id);
        CREATE TRIGGER IF NOT EXISTS validate_condition_evidence_passport
        BEFORE INSERT ON condition_evidence
        WHEN (SELECT passport_id FROM purchase_conditions WHERE id = NEW.condition_id)
             != (SELECT passport_id FROM evidence_items WHERE id = NEW.evidence_id)
        BEGIN
            SELECT RAISE(ABORT, 'condition and evidence must belong to the same passport');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_verification_events_no_update
        BEFORE UPDATE ON evidence_verification_events
        BEGIN
            SELECT RAISE(ABORT, 'evidence verification history is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_verification_events_no_delete
        BEFORE DELETE ON evidence_verification_events
        BEGIN
            SELECT RAISE(ABORT, 'evidence verification history is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_claims_no_update
        BEFORE UPDATE ON evidence_claims
        BEGIN
            SELECT RAISE(ABORT, 'evidence claims are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_claims_no_delete
        BEFORE DELETE ON evidence_claims
        BEGIN
            SELECT RAISE(ABORT, 'evidence claims are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_items_no_delete
        BEFORE DELETE ON evidence_items
        BEGIN
            SELECT RAISE(ABORT, 'original evidence is retained');
        END;
        CREATE TRIGGER IF NOT EXISTS dispute_evidence_scope
        BEFORE INSERT ON dispute_evidence
        WHEN COALESCE((SELECT passport_id FROM passport_disputes WHERE id=NEW.dispute_id),'')
              != COALESCE((SELECT passport_id FROM evidence_items WHERE id=NEW.evidence_id),'')
        BEGIN
            SELECT RAISE(ABORT, 'dispute evidence must belong to the same Passport');
        END;
        CREATE TRIGGER IF NOT EXISTS dispute_evidence_no_update
        BEFORE UPDATE ON dispute_evidence BEGIN
            SELECT RAISE(ABORT, 'dispute evidence associations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS dispute_evidence_no_delete
        BEFORE DELETE ON dispute_evidence BEGIN
            SELECT RAISE(ABORT, 'dispute evidence associations are immutable');
        END;
        """)
        evidence_columns = {row["name"] for row in db.execute("PRAGMA table_info(evidence_items)")}
        if "is_simulated" not in evidence_columns:
            # Existing evidence has unknown provenance. Mark current rows as
            # simulated, while retaining a non-simulated default for new rows.
            db.execute("""
                ALTER TABLE evidence_items ADD COLUMN is_simulated INTEGER NOT NULL DEFAULT 0
                CHECK(is_simulated IN (0, 1))
            """)
            db.execute("UPDATE evidence_items SET is_simulated = 1")
        # CREATE TABLE IF NOT EXISTS does not change an existing table. Add
        # ownership columns in place so existing condition rows are retained.
        condition_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(purchase_conditions)")
        }
        if "owner" not in condition_columns:
            db.execute("""
                ALTER TABLE purchase_conditions
                ADD COLUMN owner TEXT NOT NULL DEFAULT 'buyer'
                CHECK(owner IN ('buyer', 'merchant'))
            """)
        if "merchant_confirmed" not in condition_columns:
            db.execute("""
                ALTER TABLE purchase_conditions
                ADD COLUMN merchant_confirmed INTEGER NOT NULL DEFAULT 0
                CHECK(merchant_confirmed IN (0, 1))
            """)
        if "buyer_confirmed_at" not in condition_columns:
            db.execute("ALTER TABLE purchase_conditions ADD COLUMN buyer_confirmed_at TEXT")
        if "offer_snapshot_id" not in condition_columns:
            db.execute("ALTER TABLE purchase_conditions ADD COLUMN offer_snapshot_id TEXT REFERENCES offer_snapshots(id)")
        if "buyer_condition_id" not in condition_columns:
            db.execute("ALTER TABLE purchase_conditions ADD COLUMN buyer_condition_id TEXT REFERENCES purchase_conditions(id)")
        passport_columns = {row["name"] for row in db.execute("PRAGMA table_info(purchase_passports)")}
        passport_migrations = {
            "paypal_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "paypal_offer_snapshot_id": "TEXT",
            "paypal_request_id": "TEXT",
            "paypal_capture_request_id": "TEXT",
            "paypal_amount": "TEXT",
            "paypal_currency": "TEXT",
            "paypal_capture_id": "TEXT",
        }
        for column, definition in passport_migrations.items():
            if column not in passport_columns:
                db.execute(f"ALTER TABLE purchase_passports ADD COLUMN {column} {definition}")
        evidence_columns = {row["name"] for row in db.execute("PRAGMA table_info(evidence_items)")}
        evidence_migrations = {
            "original_content": "TEXT",
            "content_type": "TEXT",
            "received_at": "TEXT",
            "claimed_source_name": "TEXT",
            "claimed_source_reference": "TEXT",
            "claimed_captured_at": "TEXT",
            "source_classification": "TEXT NOT NULL DEFAULT 'legacy_unknown' CHECK(source_classification IN ('client_submitted','server_source','legacy_unknown','simulated'))",
            "content_sha256": "TEXT",
            "description": "TEXT",
            "offer_snapshot_id": "TEXT REFERENCES offer_snapshots(id)",
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'unverified' CHECK(lifecycle_state IN ('raw','unverified','verified','rejected','simulated','conflicting'))",
        }
        for column, definition in evidence_migrations.items():
            if column not in evidence_columns:
                db.execute(f"ALTER TABLE evidence_items ADD COLUMN {column} {definition}")

        event_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(evidence_verification_events)")
        }
        for column in ("verifier_identity", "verifier_version"):
            if column not in event_columns:
                db.execute(f"ALTER TABLE evidence_verification_events ADD COLUMN {column} TEXT")

        link_columns = {row["name"] for row in db.execute("PRAGMA table_info(condition_evidence)")}
        if "claim_id" not in link_columns:
            db.execute("ALTER TABLE condition_evidence ADD COLUMN claim_id TEXT REFERENCES evidence_claims(claim_id)")

        # Preserve old evidence, but never infer a verified claim or trusted
        # provenance from legacy values. Seed one migration audit event only.
        db.execute("""
            UPDATE evidence_items
            SET lifecycle_state = CASE WHEN is_simulated = 1 THEN 'simulated' ELSE 'unverified' END
            WHERE NOT EXISTS (
                SELECT 1 FROM evidence_verification_events e WHERE e.evidence_id = evidence_items.id
            )
        """)
        migration_time = utc_now()
        legacy_rows = db.execute("""
            SELECT i.id, i.is_simulated, i.lifecycle_state
            FROM evidence_items i
            WHERE NOT EXISTS (
                SELECT 1 FROM evidence_verification_events e WHERE e.evidence_id = i.id
            )
        """).fetchall()
        for row in legacy_rows:
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,from_state,to_state,actor_type,method,recorded_at,
                 proves_json,does_not_prove_json,reason)
                VALUES(?,?,NULL,?,'migration','legacy_backfill',?,'[]',?,?)
            """, (
                f"migration-{row['id']}", row["id"], row["lifecycle_state"], migration_time,
                json.dumps(["Legacy evidence has no verified scope or trustworthy provenance."]),
                "Preserved existing evidence without inferring claims.",
            ))
        db.executescript("""
        CREATE TRIGGER IF NOT EXISTS validate_condition_evidence_scope
        BEFORE INSERT ON condition_evidence
        WHEN (SELECT passport_id FROM evidence_items WHERE id = NEW.evidence_id)
               != (SELECT passport_id FROM purchase_conditions WHERE id = NEW.condition_id)
          OR (NEW.claim_id IS NOT NULL AND COALESCE(
               (SELECT evidence_id FROM evidence_claims WHERE claim_id = NEW.claim_id), '') != NEW.evidence_id)
        BEGIN
            SELECT RAISE(ABORT, 'condition, evidence and claim scope must match');
        END;
        CREATE TRIGGER IF NOT EXISTS validate_merchant_offer_condition
        BEFORE INSERT ON purchase_conditions
        WHEN NEW.offer_snapshot_id IS NOT NULL AND (
             (SELECT passport_id FROM offer_snapshots WHERE id = NEW.offer_snapshot_id) != NEW.passport_id
             OR NEW.owner != 'merchant'
             OR COALESCE((SELECT owner FROM purchase_conditions WHERE id = NEW.buyer_condition_id), '') != 'buyer'
             OR COALESCE((SELECT passport_id FROM purchase_conditions WHERE id = NEW.buyer_condition_id), '') != NEW.passport_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'seller offer condition scope must match Passport and buyer condition');
        END;
        CREATE TRIGGER IF NOT EXISTS validate_condition_evidence_scope_update
        BEFORE UPDATE OF condition_id,evidence_id,claim_id ON condition_evidence
        WHEN (SELECT passport_id FROM evidence_items WHERE id = NEW.evidence_id)
               != (SELECT passport_id FROM purchase_conditions WHERE id = NEW.condition_id)
          OR (NEW.claim_id IS NOT NULL AND COALESCE(
               (SELECT evidence_id FROM evidence_claims WHERE claim_id = NEW.claim_id), '') != NEW.evidence_id)
        BEGIN
            SELECT RAISE(ABORT, 'condition, evidence and claim scope must match');
        END;
        CREATE TRIGGER IF NOT EXISTS condition_evidence_no_update
        BEFORE UPDATE ON condition_evidence
        BEGIN
            SELECT RAISE(ABORT, 'condition evidence associations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS condition_evidence_no_delete
        BEFORE DELETE ON condition_evidence
        BEGIN
            SELECT RAISE(ABORT, 'condition evidence associations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_source_record_immutable
        BEFORE UPDATE OF passport_id,evidence_type,source_name,source_reference,captured_value,
                         captured_at,is_simulated,original_content,content_type,received_at,
                         claimed_source_name,claimed_source_reference,claimed_captured_at,source_classification,
                         content_sha256,description
        ON evidence_items
        BEGIN
            SELECT RAISE(ABORT, 'original evidence and provenance are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_state_requires_verification_event
        BEFORE UPDATE OF lifecycle_state,verification_status ON evidence_items
        WHEN (NEW.lifecycle_state IS NOT OLD.lifecycle_state
              OR NEW.verification_status IS NOT OLD.verification_status)
         AND (
              NEW.lifecycle_state = OLD.lifecycle_state
              OR NEW.verification_status != CASE NEW.lifecycle_state
                    WHEN 'raw' THEN 'unverified'
                    ELSE NEW.lifecycle_state
                 END
              OR NOT EXISTS (
                  SELECT 1
                  FROM evidence_verification_events event
                  WHERE event.evidence_id = OLD.id
                    AND event.from_state = OLD.lifecycle_state
                    AND event.to_state = NEW.lifecycle_state
                    AND event.actor_type = 'server_verifier'
                    AND length(trim(COALESCE(event.verifier_identity, ''))) > 0
                    AND length(trim(COALESCE(event.verifier_version, ''))) > 0
                    AND length(trim(event.method)) > 0
                    AND length(trim(event.recorded_at)) > 0
                    AND length(trim(COALESCE(event.reason, ''))) > 0
                    AND event.rowid = (
                        SELECT MAX(latest.rowid)
                        FROM evidence_verification_events latest
                        WHERE latest.evidence_id = OLD.id
                    )
              )
         )
        BEGIN
            SELECT RAISE(ABORT, 'evidence state changes require a matching verifier event');
        END;
        CREATE TRIGGER IF NOT EXISTS evidence_claim_requires_verified_event
        BEFORE INSERT ON evidence_claims
        WHEN COALESCE((SELECT to_state FROM evidence_verification_events
              WHERE event_id = NEW.verification_event_id AND evidence_id = NEW.evidence_id), '') != 'verified'
          OR COALESCE((SELECT lifecycle_state FROM evidence_items WHERE id = NEW.evidence_id), '') != 'verified'
          OR COALESCE((SELECT verification_status FROM evidence_items WHERE id = NEW.evidence_id), '') != 'verified'
          OR COALESCE((SELECT is_simulated FROM evidence_items WHERE id = NEW.evidence_id), 1) != 0
          OR NOT EXISTS (
              SELECT 1
              FROM json_each((
                  SELECT verified_event.proves_json
                  FROM evidence_verification_events verified_event
                  WHERE verified_event.event_id = NEW.verification_event_id
                    AND verified_event.evidence_id = NEW.evidence_id
              )) scoped_claim
              WHERE json_extract(scoped_claim.value, '$.type') = NEW.claim_type
                AND CAST(json_extract(scoped_claim.value, '$.value') AS TEXT) = NEW.claim_value
                AND COALESCE(json_extract(scoped_claim.value, '$.unit'), '') = COALESCE(NEW.unit, '')
          )
        BEGIN
            SELECT RAISE(ABORT, 'evidence claims require a matching verified event and claim scope');
        END;
        """)


MAX_EVIDENCE_BYTES = 64 * 1024
class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=MAX_EVIDENCE_BYTES)
    content_type: Literal["text/plain", "application/json"]
    claimed_source_name: str | None = Field(default=None, max_length=160)
    claimed_source_reference: str | None = Field(default=None, max_length=2048)
    claimed_captured_at: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    condition_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("content")
    @classmethod
    def bounded_utf8_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        if len(value.encode("utf-8")) > MAX_EVIDENCE_BYTES:
            raise ValueError("content exceeds the 65536-byte limit")
        return value

    @field_validator("claimed_source_name", "claimed_source_reference", "claimed_captured_at", "description")
    @classmethod
    def optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank when provided")
        return value

    @field_validator("condition_ids")
    @classmethod
    def unique_condition_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("condition_ids must be unique")
        if any(not item or len(item) > 64 for item in value):
            raise ValueError("condition_ids must be non-empty strings of at most 64 characters")
        return value

    @model_validator(mode="after")
    def valid_json_content(self):
        if self.content_type == "application/json":
            try:
                json.loads(self.content)
            except json.JSONDecodeError as error:
                raise ValueError("content must be valid JSON for application/json") from error
        return self


class SellerOfferCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_id: str = Field(min_length=1, max_length=64)
    seller_confirms: bool
    seller_value: str = Field(min_length=1, max_length=1000)
    evidence_content: str = Field(min_length=1, max_length=MAX_EVIDENCE_BYTES)
    evidence_description: str | None = Field(default=None, max_length=1000)
    # This is a one-way downgrade for explicitly labelled demo fixtures. It
    # can never make submitted evidence more trustworthy.
    is_simulated: bool = False

    @field_validator("seller_value", "evidence_content")
    @classmethod
    def seller_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("evidence_content")
    @classmethod
    def seller_evidence_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_EVIDENCE_BYTES:
            raise ValueError("evidence_content exceeds the 65536-byte limit")
        return value


class SellerOfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_name: str = Field(min_length=1, max_length=200)
    seller_name: str = Field(min_length=1, max_length=200)
    product_url: str | None = Field(default=None, max_length=2048)
    displayed_price: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    delivery_promise: str | None = Field(default=None, max_length=500)
    return_terms: str | None = Field(default=None, max_length=2000)
    conditions: list[SellerOfferCondition] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_offer_text_and_unique_condition_ids(self):
        for field_name in ("product_name", "seller_name"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        ids = [condition.condition_id for condition in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("conditions must contain unique condition IDs")
        return self


class EvidenceRead(BaseModel):
    id: str
    passport_id: str
    evidence_type: str
    source_name: str
    source_reference: str | None
    claimed_source_name: str | None
    claimed_source_reference: str | None
    claimed_captured_at: str | None
    source_classification: str
    content_type: str | None
    received_at: str | None
    captured_at: str
    content_sha256: str | None
    description: str | None
    lifecycle_state: str
    verification_status: str
    is_simulated: bool
    associated_conditions: list[dict]
    claims: list[dict]
    verification_history: list[dict]
    limitations: list[str]
    original_content: str | None = None


class DisputeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_id: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=5, max_length=3000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("summary")
    @classmethod
    def dispute_summary_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value.strip()

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value


class ConditionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_type: str = Field(min_length=1, max_length=80)
    operator: str = Field(min_length=1, max_length=32)
    expected_value: str = Field(min_length=1, max_length=1000)
    unit: str | None = Field(default=None, max_length=40)
    owner: Literal['buyer', 'merchant'] = 'buyer'
    hard_or_soft: Literal['hard', 'soft']
    buyer_confirmed: bool = False
    merchant_confirmed: bool = False
    evidence_status: Literal['unverified', 'supported', 'contradicted', 'unknown'] = 'unverified'

    @field_validator('condition_type', 'operator', 'expected_value')
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must not be blank')
        return value.strip()


class PassportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer_intent: str = Field(min_length=1, max_length=5000)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    status: Literal['draft', 'active', 'fulfilled', 'disputed', 'cancelled'] = 'draft'

    @field_validator('buyer_intent')
    @classmethod
    def intent_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must not be blank')
        return value.strip()


class ConditionRead(ConditionCreate):
    id: str
    passport_id: str
    buyer_confirmed_at: str | None = None
    offer_snapshot_id: str | None = None
    buyer_condition_id: str | None = None


class ReviewedCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_type: str = Field(min_length=1, max_length=80)
    operator: str = Field(min_length=1, max_length=32)
    expected_value: str = Field(min_length=1, max_length=1000)
    unit: str | None = Field(..., max_length=40)
    hard_or_soft: Literal["hard", "soft"]
    supporting_quote: str = Field(min_length=1, max_length=1000)

    @field_validator("condition_type", "operator", "expected_value")
    @classmethod
    def reviewed_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("supporting_quote")
    @classmethod
    def quote_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ConfirmIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer_intent: str = Field(min_length=1, max_length=5000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    conditions: list[ReviewedCondition] = Field(min_length=1, max_length=100)
    buyer_acknowledged: Literal[True]

    @field_validator("buyer_intent")
    @classmethod
    def confirmation_intent_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_reviewed_conditions(self):
        from decimal import Decimal, InvalidOperation
        for condition in self.conditions:
            if condition.condition_type not in CONDITION_TYPES:
                raise ValueError(f"unsupported condition type: {condition.condition_type}")
            operators = NUMERIC_OPERATORS if condition.condition_type in NUMERIC_TYPES else TEXT_OPERATORS
            if condition.operator not in operators:
                raise ValueError(f"unsupported operator for condition type: {condition.operator}")
            if condition.supporting_quote not in self.buyer_intent:
                raise ValueError("supporting_quote must be an exact substring of buyer_intent")
            if condition.condition_type in NUMERIC_TYPES:
                try:
                    value = Decimal(condition.expected_value)
                except InvalidOperation as error:
                    raise ValueError("numeric condition expected_value must be a valid number") from error
                if not value.is_finite() or (condition.condition_type == "price" and value < 0):
                    raise ValueError("numeric condition expected_value is invalid")
                if condition.condition_type in {"quantity", "delivery_days"} and value != value.to_integral_value():
                    raise ValueError(f"{condition.condition_type} must be a whole number")
            if condition.condition_type == "price" and condition.unit != self.currency:
                raise ValueError("price condition unit must match Passport currency")

        # Reject contradictory equalities and impossible bounds for the same quantity.
        groups: dict[tuple[str, str | None], list[ReviewedCondition]] = {}
        text_groups: dict[tuple[str, str | None], list[ReviewedCondition]] = {}
        for condition in self.conditions:
            if condition.condition_type in NUMERIC_TYPES:
                groups.setdefault((condition.condition_type, condition.unit), []).append(condition)
            else:
                text_groups.setdefault((condition.condition_type, condition.unit), []).append(condition)
        for group in text_groups.values():
            equalities = {c.expected_value.casefold() for c in group if c.operator == "eq"}
            exclusions = {c.expected_value.casefold() for c in group if c.operator == "ne"}
            if len(equalities) > 1 or equalities.intersection(exclusions):
                raise ValueError("conditions contain contradictory text requirements")
        for group in groups.values():
            equalities = {Decimal(c.expected_value) for c in group if c.operator == "eq"}
            exclusions = {Decimal(c.expected_value) for c in group if c.operator == "ne"}
            lowers = [(Decimal(c.expected_value), c.operator == "gt") for c in group if c.operator in {"gt", "gte"}]
            uppers = [(Decimal(c.expected_value), c.operator == "lt") for c in group if c.operator in {"lt", "lte"}]
            if len(equalities) > 1:
                raise ValueError("conditions contain contradictory numeric equalities")
            if lowers and uppers:
                lower = max(value for value, _ in lowers)
                upper = min(value for value, _ in uppers)
                lower_exclusive = any(exclusive for value, exclusive in lowers if value == lower)
                upper_exclusive = any(exclusive for value, exclusive in uppers if value == upper)
                if lower > upper or (lower == upper and (lower_exclusive or upper_exclusive)):
                    raise ValueError("conditions contain contradictory numeric bounds")
            if equalities:
                value = next(iter(equalities))
                if value in exclusions:
                    raise ValueError("conditions contain contradictory equality and inequality")
                if lowers and (value < max(v for v, _ in lowers) or
                               (value == max(v for v, _ in lowers) and any(x for v, x in lowers if v == value))):
                    raise ValueError("conditions contain contradictory equality and lower bound")
                if uppers and (value > min(v for v, _ in uppers) or
                               (value == min(v for v, _ in uppers) and any(x for v, x in uppers if v == value))):
                    raise ValueError("conditions contain contradictory equality and upper bound")
        return self


def passport_condition_unit(condition_type: str, unit: str | None, passport_currency: str) -> str | None:
    """Keep Passport currency at Passport scope for non-price conditions."""
    if condition_type != "price" and unit is not None and unit.strip().upper() == passport_currency:
        return None
    return unit


class PassportRead(BaseModel):
    id: str
    status: str
    buyer_intent: str
    currency: str
    created_at: str
    updated_at: str
    paypal_order_id: str | None
    paypal_status: str
    paypal_amount: str | None
    paypal_currency: str | None
    paypal_capture_id: str | None
    conditions: list[ConditionRead]


router = APIRouter(prefix="/api/passports", tags=["Purchase Passports"])


def passport_record(db: sqlite3.Connection, passport_id: str) -> dict | None:
    passport = db.execute("SELECT * FROM purchase_passports WHERE id = ?", (passport_id,)).fetchone()
    if passport is None:
        return None
    conditions = db.execute("SELECT * FROM purchase_conditions WHERE passport_id = ? ORDER BY rowid", (passport_id,)).fetchall()
    result = dict(passport)
    result['conditions'] = [
        {
            **dict(row),
            'buyer_confirmed': bool(row['buyer_confirmed']),
            'merchant_confirmed': bool(row['merchant_confirmed']),
        }
        for row in conditions
    ]
    return result


def offer_record(db: sqlite3.Connection, passport_id: str, offer_id: str) -> dict | None:
    row = db.execute(
        "SELECT * FROM offer_snapshots WHERE passport_id = ? AND id = ?",
        (passport_id, offer_id),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    conditions = db.execute(
        "SELECT * FROM purchase_conditions WHERE passport_id = ? AND offer_snapshot_id = ? ORDER BY rowid",
        (passport_id, offer_id),
    ).fetchall()
    result["conditions"] = []
    for condition in conditions:
        condition_data = {
            **dict(condition),
            "buyer_confirmed": bool(condition["buyer_confirmed"]),
            "merchant_confirmed": bool(condition["merchant_confirmed"]),
            "evidence": [],
        }
        evidence_rows = db.execute("""
            SELECT e.id, e.evidence_type, e.claimed_source_name, e.claimed_source_reference,
                   e.source_classification, e.received_at, e.content_sha256, e.captured_value,
                   e.lifecycle_state, e.verification_status, e.is_simulated, e.description
            FROM condition_evidence ce
            JOIN evidence_items e ON e.id = ce.evidence_id
            WHERE ce.condition_id = ? AND e.passport_id = ? AND e.offer_snapshot_id = ?
            ORDER BY e.rowid
        """, (condition["id"], passport_id, offer_id)).fetchall()
        condition_data["evidence"] = [
            {**dict(evidence), "is_simulated": bool(evidence["is_simulated"])}
            for evidence in evidence_rows
        ]
        result["conditions"].append(condition_data)
    return result


def evidence_record(db: sqlite3.Connection, passport_id: str, evidence_id: str, include_content: bool = False) -> dict | None:
    row = db.execute(
        "SELECT * FROM evidence_items WHERE passport_id = ? AND id = ?",
        (passport_id, evidence_id),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["is_simulated"] = bool(row["is_simulated"])
    result["original_content"] = row["original_content"] if include_content else None
    result["associated_conditions"] = [dict(item) for item in db.execute("""
        SELECT c.id AS condition_id, c.owner, c.condition_type, c.expected_value
        FROM condition_evidence ce
        JOIN purchase_conditions c ON c.id = ce.condition_id
        WHERE ce.evidence_id = ? AND c.passport_id = ?
        ORDER BY c.rowid
    """, (evidence_id, passport_id)).fetchall()]
    result["claims"] = [dict(item) for item in db.execute("""
        SELECT c.claim_id, c.claim_type, c.claim_value, c.unit,
               c.verification_event_id, c.created_at,
               e.to_state AS verification_state
        FROM evidence_claims c
        JOIN evidence_verification_events e ON e.event_id = c.verification_event_id
        WHERE c.evidence_id = ?
        ORDER BY c.created_at, c.rowid
    """, (evidence_id,)).fetchall()]
    history = []
    limitations = []
    for event in db.execute("""
        SELECT event_id, from_state, to_state, actor_type, actor_reference,
               method, recorded_at, proves_json, does_not_prove_json, reason
        FROM evidence_verification_events
        WHERE evidence_id = ? ORDER BY recorded_at, rowid
    """, (evidence_id,)).fetchall():
        item = dict(event)
        item["proves"] = json.loads(item.pop("proves_json"))
        item["does_not_prove"] = json.loads(item.pop("does_not_prove_json"))
        limitations.extend(item["does_not_prove"])
        history.append(item)
    result["verification_history"] = history
    result["limitations"] = list(dict.fromkeys(limitations))
    return result


@router.post("", response_model=PassportRead, status_code=201)
def create_passport(payload: PassportCreate):
    passport_id = str(uuid4())
    timestamp = utc_now()
    with connect() as db:
        db.execute(
            "INSERT INTO purchase_passports(id,status,buyer_intent,currency,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (passport_id, payload.status, payload.buyer_intent, payload.currency, timestamp, timestamp),
        )
        return passport_record(db, passport_id)


@router.post("/confirm-intent", response_model=PassportRead, status_code=201)
def confirm_reviewed_intent(payload: ConfirmIntentRequest = Body(...)):
    """Persist a buyer's explicit declaration atomically; this does not authenticate identity."""
    passport_id = str(uuid4())
    timestamp = utc_now()
    with connect() as db:
        db.execute(
            "INSERT INTO purchase_passports(id,status,buyer_intent,currency,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (passport_id, "draft", payload.buyer_intent, payload.currency, timestamp, timestamp),
        )
        for condition in payload.conditions:
            condition_unit = passport_condition_unit(
                condition.condition_type, condition.unit, payload.currency
            )
            db.execute("""
                INSERT INTO purchase_conditions
                (id,passport_id,condition_type,operator,expected_value,unit,owner,hard_or_soft,
                 buyer_confirmed,merchant_confirmed,buyer_confirmed_at,evidence_status)
                VALUES(?,?,?,?,?,?,'buyer',?,1,0,?,'unverified')
            """, (
                str(uuid4()), passport_id, condition.condition_type, condition.operator,
                condition.expected_value, condition_unit, condition.hard_or_soft, timestamp,
            ))
        return passport_record(db, passport_id)


@router.get("", response_model=list[PassportRead])
def list_passports():
    with connect() as db:
        ids = db.execute("SELECT id FROM purchase_passports ORDER BY created_at DESC, rowid DESC").fetchall()
        return [passport_record(db, row['id']) for row in ids]


@router.get("/{passport_id}", response_model=PassportRead)
def get_passport(passport_id: str):
    with connect() as db:
        result = passport_record(db, passport_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Passport not found")
    return result


@router.get("/{passport_id}/offers")
def list_seller_offers(passport_id: str):
    with connect() as db:
        if db.execute("SELECT 1 FROM purchase_passports WHERE id = ?", (passport_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        ids = db.execute(
            "SELECT id FROM offer_snapshots WHERE passport_id = ? ORDER BY captured_at DESC, rowid DESC",
            (passport_id,),
        ).fetchall()
        return [offer_record(db, passport_id, item["id"]) for item in ids]


@router.post("/{passport_id}/offers", status_code=201)
def submit_seller_offer(passport_id: str, payload: SellerOfferCreate):
    """Persist a seller declaration and raw evidence; uploads are never verified here."""
    offer_id = str(uuid4())
    captured_at = utc_now()
    with connect() as db:
        passport = db.execute(
            "SELECT currency FROM purchase_passports WHERE id = ?", (passport_id,)
        ).fetchone()
        if passport is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        if payload.currency != passport["currency"]:
            raise HTTPException(status_code=422, detail="Seller offer currency must match Passport currency")
        buyer_conditions = db.execute(
            "SELECT * FROM purchase_conditions WHERE passport_id = ? AND owner = 'buyer' ORDER BY rowid",
            (passport_id,),
        ).fetchall()
        if not buyer_conditions or any(not row["buyer_confirmed"] for row in buyer_conditions):
            raise HTTPException(status_code=409, detail="Seller offers require buyer-confirmed Passport conditions")
        buyer_by_id = {row["id"]: row for row in buyer_conditions}
        submitted_ids = {item.condition_id for item in payload.conditions}
        if submitted_ids != set(buyer_by_id):
            raise HTTPException(status_code=422, detail="Seller must respond to every buyer condition exactly once")
        for submitted in payload.conditions:
            buyer = buyer_by_id[submitted.condition_id]
            if buyer["condition_type"] in NUMERIC_TYPES:
                try:
                    stated = Decimal(submitted.seller_value)
                except InvalidOperation as error:
                    raise HTTPException(status_code=422, detail="Seller numeric condition values must be valid numbers") from error
                if not stated.is_finite():
                    raise HTTPException(status_code=422, detail="Seller numeric condition values must be finite")
                if buyer["condition_type"] == "price" and stated != Decimal(str(payload.displayed_price)):
                    raise HTTPException(status_code=422, detail="Seller price condition value must match the displayed offer price")
                if buyer["condition_type"] in {"quantity", "delivery_days"} and stated != stated.to_integral_value():
                    raise HTTPException(status_code=422, detail="Seller quantity and delivery values must be whole numbers")

        db.execute("""
            INSERT INTO offer_snapshots
            (id,passport_id,product_name,seller_name,product_url,displayed_price,currency,
             delivery_promise,return_terms,captured_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            offer_id, passport_id, payload.product_name.strip(), payload.seller_name.strip(),
            payload.product_url, payload.displayed_price, payload.currency,
            payload.delivery_promise, payload.return_terms, captured_at,
        ))

        for submitted in payload.conditions:
            buyer = buyer_by_id[submitted.condition_id]
            merchant_condition_id = str(uuid4())
            unit = passport_condition_unit(buyer["condition_type"], buyer["unit"], passport["currency"])
            db.execute("""
                INSERT INTO purchase_conditions
                (id,passport_id,condition_type,operator,expected_value,unit,owner,hard_or_soft,
                 buyer_confirmed,merchant_confirmed,buyer_confirmed_at,evidence_status,
                 offer_snapshot_id,buyer_condition_id)
                VALUES(?,?,?,?,?,?,'merchant',?,0,?,NULL,'unverified',?,?)
            """, (
                merchant_condition_id, passport_id, buyer["condition_type"], buyer["operator"],
                buyer["expected_value"], unit, buyer["hard_or_soft"],
                int(submitted.seller_confirms), offer_id, submitted.condition_id,
            ))

            evidence_id = str(uuid4())
            event_id = str(uuid4())
            digest = hashlib.sha256(submitted.evidence_content.encode("utf-8")).hexdigest()
            description = submitted.evidence_description or "Seller-submitted text; not independently verified."
            db.execute("""
                INSERT INTO evidence_items
                (id,passport_id,evidence_type,source_name,source_reference,captured_value,
                 verification_status,captured_at,is_simulated,original_content,content_type,
                 received_at,claimed_source_name,claimed_source_reference,claimed_captured_at,
                 source_classification,content_sha256,description,offer_snapshot_id,lifecycle_state)
                VALUES(?,?,'seller_offer_text','client_submitted',NULL,?,?,?,?,?,'text/plain',
                       ?,?,NULL,NULL,?,?,?,?,?)
            """, (
                evidence_id, passport_id,
                submitted.seller_value,
                'simulated' if submitted.is_simulated else 'unverified',
                captured_at, int(submitted.is_simulated),
                submitted.evidence_content, captured_at, payload.seller_name,
                'simulated' if submitted.is_simulated else 'client_submitted',
                digest, description, offer_id,
                'simulated' if submitted.is_simulated else 'raw',
            ))
            db.execute("""
                INSERT INTO evidence_verification_events
                (event_id,evidence_id,from_state,to_state,actor_type,actor_reference,method,
                 recorded_at,proves_json,does_not_prove_json,reason)
                VALUES(?,?,NULL,?,'ingestion_api',?,'seller_offer_submission',?,'[]',?,?)
            """, (
                event_id, evidence_id, 'simulated' if submitted.is_simulated else 'raw',
                payload.seller_name, captured_at,
                json.dumps([
                    "Seller identity and source authenticity are not verified.",
                    "The seller's condition assertion is not verified.",
                ]),
                "Seller text and offer assertions are preserved as unverified evidence.",
            ))
            for condition_id in (submitted.condition_id, merchant_condition_id):
                db.execute(
                    "INSERT INTO condition_evidence(condition_id,evidence_id,claim_id) VALUES(?,?,NULL)",
                    (condition_id, evidence_id),
                )

        db.execute("UPDATE purchase_passports SET updated_at = ? WHERE id = ?", (captured_at, passport_id))
        return offer_record(db, passport_id, offer_id)


@router.post("/{passport_id}/evidence", response_model=EvidenceRead, status_code=201)
def ingest_evidence(passport_id: str, payload: EvidenceCreate):
    evidence_id = str(uuid4())
    event_id = str(uuid4())
    received_at = utc_now()
    content_digest = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    not_proven = [
        "Source authenticity has not been verified.",
        "No condition claim has been verified from this content.",
    ]
    with connect() as db:
        if db.execute("SELECT 1 FROM purchase_passports WHERE id = ?", (passport_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        for condition_id in payload.condition_ids:
            condition = db.execute(
                "SELECT 1 FROM purchase_conditions WHERE id = ? AND passport_id = ?",
                (condition_id, passport_id),
            ).fetchone()
            if condition is None:
                raise HTTPException(status_code=422, detail="Every condition_id must belong to this Passport")

        db.execute("""
            INSERT INTO evidence_items
            (id,passport_id,evidence_type,source_name,source_reference,captured_value,
             verification_status,captured_at,is_simulated,original_content,content_type,
             received_at,claimed_source_name,claimed_source_reference,claimed_captured_at,
             source_classification,content_sha256,description,lifecycle_state)
            VALUES(?,?, 'text', 'client_submitted', NULL, ?, 'unverified', ?, 0, ?, ?, ?, ?, ?, ?,
                   'client_submitted', ?, ?, 'raw')
        """, (
            evidence_id, passport_id, payload.content, received_at, payload.content,
            payload.content_type, received_at, payload.claimed_source_name,
            payload.claimed_source_reference, payload.claimed_captured_at,
            content_digest, payload.description,
        ))
        db.execute("""
            INSERT INTO evidence_verification_events
            (event_id,evidence_id,from_state,to_state,actor_type,method,recorded_at,
             proves_json,does_not_prove_json,reason)
            VALUES(?,?,NULL,'raw','ingestion_api','json_text_ingestion',?,'[]',?,?)
        """, (
            event_id, evidence_id, received_at, json.dumps(not_proven),
            "Evidence is preserved but has not been verified.",
        ))
        for condition_id in payload.condition_ids:
            db.execute(
                "INSERT INTO condition_evidence(condition_id,evidence_id,claim_id) VALUES(?,?,NULL)",
                (condition_id, evidence_id),
            )
        result = evidence_record(db, passport_id, evidence_id)
    return result


@router.get("/{passport_id}/evidence", response_model=list[EvidenceRead])
def list_evidence(passport_id: str):
    with connect() as db:
        if db.execute("SELECT 1 FROM purchase_passports WHERE id = ?", (passport_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        evidence_ids = db.execute(
            "SELECT id FROM evidence_items WHERE passport_id = ? ORDER BY received_at, rowid",
            (passport_id,),
        ).fetchall()
        return [evidence_record(db, passport_id, item["id"]) for item in evidence_ids]


@router.get("/{passport_id}/evidence/{evidence_id}", response_model=EvidenceRead)
def get_evidence(passport_id: str, evidence_id: str, include_content: bool = Query(False)):
    with connect() as db:
        result = evidence_record(db, passport_id, evidence_id, include_content=include_content)
    if result is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return result


@router.post("/{passport_id}/disputes", status_code=201)
def report_dispute(passport_id: str, payload: DisputeCreate):
    """Record a buyer-declared broken promise; no identity or refund outcome is asserted."""
    dispute_id = str(uuid4())
    reported_at = utc_now()
    with connect() as db:
        if db.execute("SELECT 1 FROM purchase_passports WHERE id=?", (passport_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        if db.execute("SELECT 1 FROM purchase_conditions WHERE id=? AND passport_id=? AND owner='buyer'",
                      (payload.condition_id, passport_id)).fetchone() is None:
            raise HTTPException(status_code=422, detail="Dispute condition must be a buyer condition on this Passport")
        for evidence_id in payload.evidence_ids:
            if db.execute("SELECT 1 FROM evidence_items WHERE id=? AND passport_id=?",
                          (evidence_id, passport_id)).fetchone() is None:
                raise HTTPException(status_code=422, detail="Every dispute evidence item must belong to this Passport")
        db.execute("INSERT INTO passport_disputes(id,passport_id,condition_id,summary,reported_at,status) VALUES(?,?,?,?,?,'open')",
                   (dispute_id, passport_id, payload.condition_id, payload.summary, reported_at))
        for evidence_id in payload.evidence_ids:
            db.execute("INSERT INTO dispute_evidence(dispute_id,evidence_id) VALUES(?,?)", (dispute_id, evidence_id))
        return dispute_record(db, passport_id, dispute_id)


def dispute_record(db: sqlite3.Connection, passport_id: str, dispute_id: str) -> dict | None:
    row = db.execute("""SELECT d.*,c.owner,c.condition_type,c.expected_value
        FROM passport_disputes d JOIN purchase_conditions c ON c.id=d.condition_id
        WHERE d.id=? AND d.passport_id=?""", (dispute_id, passport_id)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["evidence"] = [dict(item) for item in db.execute("""SELECT e.id,e.evidence_type,e.claimed_source_name,
        e.claimed_source_reference,e.source_classification,e.received_at,e.content_sha256,
        e.lifecycle_state,e.verification_status,e.is_simulated
        FROM dispute_evidence de JOIN evidence_items e ON e.id=de.evidence_id
        WHERE de.dispute_id=? ORDER BY e.received_at,e.rowid""", (dispute_id,)).fetchall()]
    return result


@router.get("/{passport_id}/disputes")
def list_disputes(passport_id: str):
    with connect() as db:
        ids = db.execute("SELECT id FROM passport_disputes WHERE passport_id=? ORDER BY reported_at DESC",
                         (passport_id,)).fetchall()
        if not ids and db.execute("SELECT 1 FROM purchase_passports WHERE id=?", (passport_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        return [dispute_record(db, passport_id, row["id"]) for row in ids]


def evaluate_passport_state(db: sqlite3.Connection, passport_id: str, offer_id: str | None = None) -> PassportDecision:
    passport = db.execute("SELECT id FROM purchase_passports WHERE id = ?", (passport_id,)).fetchone()
    if passport is None:
        raise HTTPException(status_code=404, detail="Passport not found")
    if offer_id is not None and db.execute(
        "SELECT 1 FROM offer_snapshots WHERE id = ? AND passport_id = ?", (offer_id, passport_id)
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail="Seller offer not found")

    if offer_id is None:
        condition_rows = db.execute(
            "SELECT * FROM purchase_conditions WHERE passport_id = ? ORDER BY rowid", (passport_id,)
        ).fetchall()
    else:
        condition_rows = db.execute("""
            SELECT * FROM purchase_conditions
            WHERE passport_id = ? AND (owner = 'buyer' OR offer_snapshot_id = ?)
            ORDER BY rowid
        """, (passport_id, offer_id)).fetchall()
    conditions = [dict(row) for row in condition_rows]
    linked_evidence = db.execute("""
            SELECT ce.condition_id, e.id, e.verification_status, e.lifecycle_state,
                   e.is_simulated, c.claim_id, c.claim_type, c.claim_value,
                   ve.to_state AS verification_event_state
            FROM condition_evidence ce
            JOIN evidence_items e ON e.id = ce.evidence_id
            JOIN purchase_conditions pc
              ON pc.id = ce.condition_id AND pc.passport_id = e.passport_id
            LEFT JOIN evidence_claims c ON c.claim_id = ce.claim_id AND c.evidence_id = e.id
            LEFT JOIN evidence_verification_events ve
                   ON ve.event_id = c.verification_event_id AND ve.evidence_id = e.id
            WHERE e.passport_id = ?
              AND (? IS NULL OR e.offer_snapshot_id IS NULL OR e.offer_snapshot_id = ?)
            ORDER BY e.rowid
        """, (passport_id, offer_id, offer_id)).fetchall()

    evidence_by_condition: dict[str, list[dict]] = {}
    for row in linked_evidence:
        evidence_by_condition.setdefault(row["condition_id"], []).append({
            "id": row["id"],
            "verification_status": row["verification_status"],
            "lifecycle_state": row["lifecycle_state"],
            "is_simulated": bool(row["is_simulated"]),
            "claim_id": row["claim_id"],
            "claim_type": row["claim_type"],
            "claim_value": row["claim_value"],
            "verification_event_state": row["verification_event_state"],
        })
    result = evaluate_conditions(passport_id, conditions, evidence_by_condition)
    return apply_fulfilment_risk(result, conditions)


@router.post("/{passport_id}/evaluate", response_model=PassportDecision)
async def evaluate_passport(
    passport_id: str,
    request: Request,
    offer_id: str | None = Query(None, max_length=64),
):
    if await request.body():
        raise HTTPException(status_code=422, detail="Evaluation uses persisted evidence and accepts no request body")
    with connect() as db:
        return evaluate_passport_state(db, passport_id, offer_id)


@router.post("/{passport_id}/conditions", response_model=list[ConditionRead], status_code=201)
def add_conditions(passport_id: str, conditions: list[ConditionCreate] = Body(min_length=1, max_length=100)):
    timestamp = utc_now()
    with connect() as db:
        passport = db.execute(
            "SELECT currency FROM purchase_passports WHERE id = ?", (passport_id,)
        ).fetchone()
        if passport is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        for condition in conditions:
            condition_unit = passport_condition_unit(
                condition.condition_type, condition.unit, passport["currency"]
            )
            db.execute(
                "INSERT INTO purchase_conditions(id,passport_id,condition_type,operator,expected_value,unit,owner,hard_or_soft,buyer_confirmed,merchant_confirmed,buyer_confirmed_at,evidence_status) VALUES(?,?,?,?,?,?,?,?,0,0,NULL,?)",
                (str(uuid4()), passport_id, condition.condition_type, condition.operator,
                 condition.expected_value, condition_unit, condition.owner, condition.hard_or_soft,
                 condition.evidence_status),
            )
        db.execute("UPDATE purchase_passports SET updated_at = ? WHERE id = ?", (timestamp, passport_id))
        rows = db.execute("SELECT * FROM purchase_conditions WHERE passport_id = ? ORDER BY rowid", (passport_id,)).fetchall()
        return [
            {
                **dict(row),
                'buyer_confirmed': bool(row['buyer_confirmed']),
                'merchant_confirmed': bool(row['merchant_confirmed']),
            }
            for row in rows
        ]

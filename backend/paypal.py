"""PayPal sandbox REST service and checkout routes for Purchase Passports."""

from __future__ import annotations

import base64
import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.passports import connect, evaluate_passport_state, utc_now


DEFAULT_PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"
PAYPAL_SUPPORTED_CURRENCIES = frozenset({
    "AUD", "BRL", "CAD", "CNY", "CZK", "DKK", "EUR", "HKD", "HUF", "ILS", "JPY",
    "MYR", "MXN", "TWD", "NZD", "NOK", "PHP", "PLN", "GBP", "RUB", "SGD", "SEK", "CHF", "THB", "USD",
})
router = APIRouter(prefix="/api", tags=["PayPal Sandbox"])


class PayPalError(Exception):
    """Provider failure with no secrets or response body attached."""


class PayPalConfigurationError(Exception):
    pass


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: str = Field(min_length=1, max_length=64)


class CaptureOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=64)


def paypal_configuration() -> dict[str, Any]:
    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    base_url = os.getenv("PAYPAL_BASE_URL", DEFAULT_PAYPAL_BASE_URL).strip().rstrip("/")
    parsed = urlparse(base_url)
    # This phase is sandbox-only. The base URL remains configurable for
    # sandbox-compatible test environments, but production PayPal is rejected.
    allowed_hosts = {"api-m.sandbox.paypal.com"}
    valid_base = (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
    )
    return {
        "configured": bool(client_id and client_secret and valid_base),
        "client_id": client_id or None,
        "client_secret": client_secret or None,
        "base_url": base_url if valid_base else None,
        "mode": "sandbox",
        "missing": [
            name for name, value in (
                ("PAYPAL_CLIENT_ID", client_id),
                ("PAYPAL_CLIENT_SECRET", client_secret),
                ("PAYPAL_BASE_URL", base_url if valid_base else ""),
            ) if not value
        ],
        "webhook_configured": bool(client_id and client_secret and valid_base and os.getenv("PAYPAL_WEBHOOK_ID", "").strip()),
    }


def _http_json_request(method: str, url: str, headers: dict[str, str], payload: dict | None = None) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Accept": "application/json", **headers},
        method=method,
    )
    try:
        with urlopen(request, timeout=45) as response:
            content = response.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise PayPalError
            result = json.loads(content.decode("utf-8"))
            if not isinstance(result, dict):
                raise PayPalError
            return result
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        # Do not include provider bodies, credentials, or request headers in logs/errors.
        raise PayPalError from error


def _request_access_token(config: dict[str, Any]) -> str:
    credentials = f"{config['client_id']}:{config['client_secret']}".encode("utf-8")
    request = Request(
        f"{config['base_url']}/v1/oauth2/token",
        data=b"grant_type=client_credentials",
        headers={
            "Accept": "application/json",
            "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            content = response.read(128 * 1024 + 1)
            if len(content) > 128 * 1024:
                raise PayPalError
            result = json.loads(content.decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PayPalError from error
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise PayPalError
    return token


def _authorized_request(config: dict[str, Any], method: str, path: str, payload: dict | None = None,
                        request_id: str | None = None) -> dict:
    token = _request_access_token(config)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    return _http_json_request(method, f"{config['base_url']}{path}", headers, payload)


def _order_amount(order: dict) -> tuple[str, str]:
    units = order.get("purchase_units")
    if not isinstance(units, list) or len(units) != 1:
        raise PayPalError
    amount = units[0].get("amount") if isinstance(units[0], dict) else None
    if not isinstance(amount, dict):
        raise PayPalError
    value, currency = amount.get("value"), amount.get("currency_code")
    if not isinstance(value, str) or not isinstance(currency, str):
        raise PayPalError
    try:
        numeric = Decimal(value)
    except InvalidOperation as error:
        raise PayPalError from error
    if not numeric.is_finite() or numeric <= 0:
        raise PayPalError
    return format(numeric, "f"), currency


def _verified_provider_order(order: dict, order_id: str, amount: str, currency: str) -> None:
    if order.get("id") != order_id:
        raise PayPalError
    provider_amount, provider_currency = _order_amount(order)
    if Decimal(provider_amount) != Decimal(amount) or provider_currency != currency:
        raise PayPalError


def create_paypal_order(amount: str, currency: str, request_id: str) -> dict:
    config = paypal_configuration()
    if not config["configured"]:
        raise PayPalConfigurationError
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": currency, "value": amount},
        }],
        "application_context": {"shipping_preference": "NO_SHIPPING"},
    }
    result = _authorized_request(config, "POST", "/v2/checkout/orders", payload, request_id)
    order_id = result.get("id")
    provider_amount, provider_currency = _order_amount(result)
    if (not isinstance(order_id, str) or not order_id
            or Decimal(provider_amount) != Decimal(amount) or provider_currency != currency):
        raise PayPalError
    if result.get("status") not in {"CREATED", "PAYER_ACTION_REQUIRED"}:
        raise PayPalError
    return result


def get_paypal_order(order_id: str) -> dict:
    config = paypal_configuration()
    if not config["configured"]:
        raise PayPalConfigurationError
    result = _authorized_request(config, "GET", f"/v2/checkout/orders/{order_id}")
    if result.get("id") != order_id:
        raise PayPalError
    return result


def capture_paypal_order(order_id: str, request_id: str) -> dict:
    config = paypal_configuration()
    if not config["configured"]:
        raise PayPalConfigurationError
    result = _authorized_request(
        config, "POST", f"/v2/checkout/orders/{order_id}/capture", {}, request_id
    )
    if result.get("id") != order_id:
        raise PayPalError
    return result


def _amount_for_offer(displayed_price: float, currency: str) -> str:
    if currency not in PAYPAL_SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="This currency is not supported by the PayPal Orders API integration")
    try:
        amount = Decimal(str(displayed_price))
    except InvalidOperation as error:
        raise HTTPException(status_code=422, detail="Seller offer amount is invalid") from error
    if not amount.is_finite() or amount <= 0 or amount.adjusted() > 13:
        raise HTTPException(status_code=422, detail="Seller offer amount is invalid")
    zero_decimal_currencies = {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
    decimals = 0 if currency in zero_decimal_currencies else 2
    quantizer = Decimal("1") if decimals == 0 else Decimal("0.01")
    try:
        normalized = amount.quantize(quantizer)
    except InvalidOperation as error:
        raise HTTPException(status_code=422, detail="Seller offer amount is invalid") from error
    if normalized != amount:
        raise HTTPException(status_code=422, detail="Seller offer amount has unsupported currency precision")
    return format(normalized, f".{decimals}f")


@router.get("/paypal/config")
def public_paypal_config():
    config = paypal_configuration()
    return {
        "configured": config["configured"],
        "client_id": config["client_id"] if config["configured"] else None,
        "mode": config["mode"],
        "missing": config["missing"],
        "webhook_configured": config["webhook_configured"],
        "supported_currencies": sorted(PAYPAL_SUPPORTED_CURRENCIES),
    }


@router.post("/passports/{passport_id}/paypal/order")
def create_passport_paypal_order(passport_id: str, payload: CreateOrderRequest):
    config = paypal_configuration()
    if not config["configured"]:
        raise HTTPException(status_code=503, detail={
            "message": "PayPal sandbox is not configured.",
            "required_environment": config["missing"],
        })

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        passport = db.execute("SELECT * FROM purchase_passports WHERE id = ?", (passport_id,)).fetchone()
        offer = db.execute(
            "SELECT * FROM offer_snapshots WHERE id = ? AND passport_id = ?",
            (payload.offer_id, passport_id),
        ).fetchone()
        if passport is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        if offer is None:
            raise HTTPException(status_code=404, detail="Seller offer not found")
        decision = evaluate_passport_state(db, passport_id, payload.offer_id)
        if decision.outcome != "APPROVE":
            raise HTTPException(status_code=409, detail={
                "message": "Checkout is blocked unless the persisted Passport decision is APPROVE.",
                "outcome": decision.outcome,
                "reasons": decision.reasons,
            })
        if passport["paypal_status"] == "captured":
            raise HTTPException(status_code=409, detail="This Passport already has a completed PayPal payment")
        if passport["paypal_status"] == "creating":
            raise HTTPException(status_code=409, detail="PayPal order creation is already in progress")
        if passport["paypal_status"] == "created":
            if passport["paypal_offer_snapshot_id"] != payload.offer_id:
                raise HTTPException(status_code=409, detail="Cancel the existing PayPal order before selecting another offer")
            return {
                "order_id": passport["paypal_order_id"],
                "amount": passport["paypal_amount"],
                "currency": passport["paypal_currency"],
                "status": passport["paypal_status"],
                "mode": config["mode"],
            }

        amount = _amount_for_offer(offer["displayed_price"], offer["currency"])
        if offer["currency"] != passport["currency"]:
            raise HTTPException(status_code=409, detail="Seller offer currency no longer matches Passport currency")
        request_id = passport["paypal_request_id"] if (
            passport["paypal_status"] == "failed"
            and passport["paypal_offer_snapshot_id"] == payload.offer_id
            and passport["paypal_request_id"]
        ) else str(uuid4())
        db.execute("""
            UPDATE purchase_passports
            SET paypal_status='creating',paypal_offer_snapshot_id=?,paypal_request_id=?,
                paypal_amount=?,paypal_currency=?,updated_at=?
            WHERE id=?
        """, (payload.offer_id, request_id, amount, offer["currency"], utc_now(), passport_id))

    try:
        provider_order = create_paypal_order(amount, offer["currency"], request_id)
    except PayPalConfigurationError as error:
        with connect() as db:
            db.execute("UPDATE purchase_passports SET paypal_status='failed' WHERE id=?", (passport_id,))
        raise HTTPException(status_code=503, detail="PayPal sandbox configuration is invalid") from error
    except PayPalError as error:
        with connect() as db:
            db.execute("UPDATE purchase_passports SET paypal_status='failed' WHERE id=?", (passport_id,))
        raise HTTPException(status_code=502, detail="PayPal order creation failed; provider details were suppressed") from error

    provider_order_id = provider_order["id"]
    with connect() as db:
        db.execute("""
            UPDATE purchase_passports
            SET paypal_order_id=?,paypal_status='created',updated_at=?
            WHERE id=? AND paypal_request_id=? AND paypal_status='creating'
        """, (provider_order_id, utc_now(), passport_id, request_id))
        stored = db.execute("SELECT paypal_status FROM purchase_passports WHERE id=?", (passport_id,)).fetchone()
        if stored is None or stored["paypal_status"] != "created":
            raise HTTPException(status_code=409, detail="Passport PayPal order state changed")
    return {
        "order_id": provider_order_id,
        "amount": amount,
        "currency": offer["currency"],
        "status": "created",
        "mode": config["mode"],
    }


@router.post("/passports/{passport_id}/paypal/capture")
def capture_passport_paypal_order(passport_id: str, payload: CaptureOrderRequest):
    config = paypal_configuration()
    if not config["configured"]:
        raise HTTPException(status_code=503, detail="PayPal sandbox is not configured")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        passport = db.execute("SELECT * FROM purchase_passports WHERE id=?", (passport_id,)).fetchone()
        if passport is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        if passport["paypal_order_id"] != payload.order_id:
            raise HTTPException(status_code=422, detail="PayPal order does not belong to this Passport")
        if passport["paypal_status"] == "captured":
            return {
                "status": "COMPLETED",
                "order_id": payload.order_id,
                "capture_id": passport["paypal_capture_id"],
                "amount": passport["paypal_amount"],
                "currency": passport["paypal_currency"],
            }
        if passport["paypal_status"] != "created":
            raise HTTPException(status_code=409, detail="PayPal order is not ready for capture")
        offer_id = passport["paypal_offer_snapshot_id"]
        expected_amount = passport["paypal_amount"]
        expected_currency = passport["paypal_currency"]
        capture_request_id = passport["paypal_capture_request_id"] or str(uuid4())
        if passport["paypal_capture_request_id"] is None:
            # Persist the provider idempotency key before making the capture
            # request so a lost response can be safely retried with the same key.
            db.execute(
                "UPDATE purchase_passports SET paypal_capture_request_id=? WHERE id=?",
                (capture_request_id, passport_id),
            )

    try:
        remote_order = get_paypal_order(payload.order_id)
        _verified_provider_order(remote_order, payload.order_id, expected_amount, expected_currency)
    except PayPalConfigurationError as error:
        raise HTTPException(status_code=503, detail="PayPal sandbox configuration is invalid") from error
    except PayPalError as error:
        raise HTTPException(status_code=502, detail="PayPal order validation failed; provider details were suppressed") from error
    if remote_order.get("status") != "APPROVED":
        raise HTTPException(status_code=409, detail="PayPal requires buyer approval before capture")

    try:
        # Lock Passport state while re-evaluating and submitting the capture request.
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            passport = db.execute("SELECT * FROM purchase_passports WHERE id=?", (passport_id,)).fetchone()
            if passport is None or passport["paypal_order_id"] != payload.order_id or passport["paypal_status"] != "created":
                raise HTTPException(status_code=409, detail="PayPal order state changed before capture")
            offer = db.execute("SELECT displayed_price,currency FROM offer_snapshots WHERE id=? AND passport_id=?",
                               (offer_id, passport_id)).fetchone()
            if (offer is None or offer["currency"] != expected_currency
                    or _amount_for_offer(offer["displayed_price"], offer["currency"]) != expected_amount):
                raise HTTPException(status_code=409, detail="Selected seller offer amount or currency changed after order creation")
            decision = evaluate_passport_state(db, passport_id, offer_id)
            if decision.outcome != "APPROVE":
                raise HTTPException(status_code=409, detail={
                    "message": "Capture blocked because the Passport is no longer approved.",
                    "outcome": decision.outcome,
                    "reasons": decision.reasons,
                })
            capture_result = capture_paypal_order(payload.order_id, capture_request_id)
            if capture_result.get("id") != payload.order_id:
                raise PayPalError
            units = capture_result.get("purchase_units")
            captures = units[0].get("payments", {}).get("captures", []) if units else []
            if capture_result.get("status") == "PENDING":
                pending = [item for item in captures if item.get("status") == "PENDING"] if isinstance(captures, list) else []
                if len(pending) != 1 or not isinstance(pending[0].get("id"), str):
                    raise PayPalError
                capture_id = pending[0]["id"]
                pending_amount, pending_currency = _order_amount({"purchase_units": [{"amount": pending[0].get("amount")}]})
                if Decimal(pending_amount) != Decimal(expected_amount) or pending_currency != expected_currency:
                    raise PayPalError
                db.execute("UPDATE purchase_passports SET paypal_status='pending',paypal_capture_id=?,updated_at=? WHERE id=? AND paypal_order_id=? AND paypal_status='created'",
                           (capture_id, utc_now(), passport_id, payload.order_id))
                response_state = "PENDING"
            elif capture_result.get("status") == "DECLINED":
                capture_id = None
                db.execute("UPDATE purchase_passports SET paypal_status='declined',updated_at=? WHERE id=? AND paypal_order_id=?",
                           (utc_now(), passport_id, payload.order_id))
                response_state = "DECLINED"
            elif capture_result.get("status") == "COMPLETED":
                completed = [item for item in captures if item.get("status") == "COMPLETED"] if isinstance(captures, list) else []
                if len(completed) != 1 or not isinstance(completed[0].get("id"), str):
                    raise PayPalError
                capture_id = completed[0]["id"]
                capture_amount, capture_currency = _order_amount({"purchase_units": [{"amount": completed[0].get("amount")}]})
                if Decimal(capture_amount) != Decimal(expected_amount) or capture_currency != expected_currency:
                    raise PayPalError
                db.execute("""UPDATE purchase_passports
                    SET paypal_status='captured',paypal_capture_id=?,updated_at=?
                    WHERE id=? AND paypal_order_id=? AND paypal_status='created'""",
                    (capture_id, utc_now(), passport_id, payload.order_id))
                response_state = "COMPLETED"
            else:
                raise PayPalError
    except PayPalConfigurationError as error:
        raise HTTPException(status_code=503, detail="PayPal sandbox configuration is invalid") from error
    except PayPalError as error:
        raise HTTPException(status_code=502, detail="PayPal capture failed or could not be verified") from error

    return JSONResponse(status_code=202 if response_state == "PENDING" else 402 if response_state == "DECLINED" else 200, content={
        "status": response_state,
        "order_id": payload.order_id,
        "capture_id": capture_id,
        "amount": expected_amount,
        "currency": expected_currency,
    })


@router.post("/passports/{passport_id}/paypal/cancel")
def cancel_passport_paypal_order(passport_id: str, payload: CaptureOrderRequest):
    with connect() as db:
        passport = db.execute("SELECT * FROM purchase_passports WHERE id=?", (passport_id,)).fetchone()
        if passport is None:
            raise HTTPException(status_code=404, detail="Passport not found")
        if passport["paypal_order_id"] != payload.order_id:
            raise HTTPException(status_code=422, detail="PayPal order does not belong to this Passport")
        if passport["paypal_status"] == "captured":
            raise HTTPException(status_code=409, detail="A completed PayPal payment cannot be cancelled")
        if passport["paypal_status"] not in {"created", "cancelled"}:
            raise HTTPException(status_code=409, detail="PayPal order is not cancellable")
        db.execute(
            "UPDATE purchase_passports SET paypal_status='cancelled',updated_at=? WHERE id=?",
            (utc_now(), passport_id),
        )
    return {"order_id": payload.order_id, "status": "CANCELLED"}


@router.post("/paypal/webhooks")
async def paypal_webhook(request: Request):
    """Ask PayPal to verify each transmission before reconciling capture state."""
    config = paypal_configuration()
    webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
    if not config["configured"] or not webhook_id:
        raise HTTPException(status_code=503, detail="PayPal webhook verification is not configured")
    raw_body = await request.body()
    if len(raw_body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload exceeds the size limit")
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook payload") from error
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not isinstance(event.get("event_type"), str):
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook event")
    header_names = {
        "auth_algo": "paypal-auth-algo",
        "cert_url": "paypal-cert-url",
        "transmission_id": "paypal-transmission-id",
        "transmission_sig": "paypal-transmission-sig",
        "transmission_time": "paypal-transmission-time",
    }
    signature_data = {key: request.headers.get(header) for key, header in header_names.items()}
    if any(not value for value in signature_data.values()):
        raise HTTPException(status_code=400, detail="PayPal webhook signature headers are incomplete")
    try:
        verification = _authorized_request(config, "POST", "/v1/notifications/verify-webhook-signature", {
            **signature_data, "webhook_id": webhook_id, "webhook_event": event,
        })
    except (PayPalConfigurationError, PayPalError) as error:
        raise HTTPException(status_code=502, detail="PayPal webhook signature verification failed") from error
    if verification.get("verification_status") != "SUCCESS":
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature")

    event_type = event["event_type"]
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    supplementary = resource.get("supplementary_data") if isinstance(resource.get("supplementary_data"), dict) else {}
    related_ids = supplementary.get("related_ids") if isinstance(supplementary.get("related_ids"), dict) else {}
    order_id = related_ids.get("order_id")
    capture_id = resource.get("id")
    amount = resource.get("amount") if isinstance(resource.get("amount"), dict) else {}
    if event_type == "PAYMENT.CAPTURE.COMPLETED" and (
        resource.get("status") != "COMPLETED" or not isinstance(order_id, str)
        or not isinstance(capture_id, str) or not isinstance(amount.get("value"), str)
        or not isinstance(amount.get("currency_code"), str)
    ):
        raise HTTPException(status_code=400, detail="Completed capture webhook lacks validated order details")

    now = utc_now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM paypal_webhook_events WHERE event_id=?", (event["id"],)).fetchone():
            return {"received": True, "duplicate": True}
        passport = db.execute("SELECT * FROM purchase_passports WHERE paypal_order_id=?", (order_id,)).fetchone() if order_id else None
        processing_status = "ignored"
        processed_at = None
        if event_type == "PAYMENT.CAPTURE.COMPLETED" and passport is not None:
            try:
                amount_matches = Decimal(amount["value"]) == Decimal(passport["paypal_amount"])
            except (InvalidOperation, TypeError):
                amount_matches = False
            if not amount_matches or amount["currency_code"] != passport["paypal_currency"]:
                raise HTTPException(status_code=409, detail="Webhook amount or currency does not match the recorded order")
            if passport["paypal_status"] not in {"created", "pending", "captured"}:
                raise HTTPException(status_code=409, detail="Webhook capture does not match the recorded payment state")
            if passport["paypal_capture_id"] not in {None, capture_id}:
                raise HTTPException(status_code=409, detail="A different capture is already recorded")
            db.execute("""UPDATE purchase_passports SET paypal_status='captured',paypal_capture_id=?,updated_at=?
                          WHERE id=? AND paypal_order_id=?""", (capture_id, now, passport["id"], order_id))
            processing_status = "processed"
            processed_at = now
        db.execute("""INSERT INTO paypal_webhook_events
                      (event_id,event_type,order_id,received_at,processed_at,processing_status)
                      VALUES(?,?,?,?,?,?)""", (event["id"], event_type, order_id, now, processed_at, processing_status))
    return {"received": True, "processed": processing_status == "processed"}

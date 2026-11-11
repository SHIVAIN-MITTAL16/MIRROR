"""Password and opaque-cookie session authentication for MIRROR prototype users."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
password_hash = PasswordHash.recommended()
SESSION_COOKIE = "mirror_session"
CSRF_COOKIE = "mirror_csrf"
SESSION_TTL = timedelta(hours=12)


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["buyer", "seller"]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if value.count("@") != 1 or any(ch.isspace() for ch in value):
            raise ValueError("email must be a valid address")
        local, _, domain = value.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must be a valid address")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class SessionUser(BaseModel):
    id: str
    email: str
    role: str
    seller_id: str | None = None


def _db_helpers():
    from backend.passports import connect, utc_now
    return connect, utc_now


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cookie_options(request: Request) -> dict:
    return {"httponly": True, "secure": request.url.scheme == "https", "samesite": "strict", "path": "/"}


def _set_session(response: Response, request: Request, user: dict) -> dict:
    connect, _ = _db_helpers()
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = (now + SESSION_TTL).isoformat()
    with connect() as db:
        db.execute("INSERT INTO auth_sessions(id,user_id,token_hash,csrf_hash,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                   (str(uuid4()), user["id"], _token_digest(session_token), _token_digest(csrf_token), now.isoformat(), expires))
    options = _cookie_options(request)
    response.set_cookie(SESSION_COOKIE, session_token, max_age=int(SESSION_TTL.total_seconds()), **options)
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=int(SESSION_TTL.total_seconds()), httponly=False,
                        secure=options["secure"], samesite="strict", path="/")
    return {"user": {"id": user["id"], "email": user["email"], "role": user["role"], "seller_id": user.get("seller_id")},
            "expires_at": expires}


def authenticate_request(request: Request, *, require_csrf: bool = True) -> dict:
    connect, utc_now = _db_helpers()
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    with connect() as db:
        row = db.execute("""SELECT u.id,u.email,u.role,u.disabled_at,s.id AS seller_id,ss.csrf_hash,ss.expires_at,ss.revoked_at
            FROM auth_sessions ss JOIN auth_users u ON u.id=ss.user_id
            LEFT JOIN seller_accounts s ON s.user_id=u.id
            WHERE ss.token_hash=?""", (_token_digest(token),)).fetchone()
    if row is None or row["revoked_at"] is not None or row["disabled_at"] is not None:
        raise HTTPException(status_code=401, detail="Session is invalid or revoked")
    try:
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Session has expired")
    if require_csrf and request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
        csrf_header = request.headers.get("X-Mirror-CSRF", "")
        if (not csrf_cookie or not secrets.compare_digest(csrf_cookie, csrf_header)
                or not secrets.compare_digest(_token_digest(csrf_cookie), row["csrf_hash"])):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") not in {
            item.strip().rstrip("/") for item in os.getenv("MIRROR_CORS_ORIGINS", "http://127.0.0.1:5501").split(",")
        }:
            raise HTTPException(status_code=403, detail="Request origin is not allowed")
    return {"id": row["id"], "email": row["email"], "role": row["role"], "seller_id": row["seller_id"]}


def require_authenticated(request: Request) -> dict:
    user = authenticate_request(request)
    request.state.user = user
    return user


def require_role(user: dict, role: str) -> None:
    if user.get("role") != role:
        raise HTTPException(status_code=403, detail=f"{role.capitalize()} role required")


@router.post("/register", status_code=201)
def register(payload: RegistrationRequest, request: Request, response: Response):
    connect, utc_now = _db_helpers()
    email = payload.email
    _check_auth_origin(request)
    user_id = str(uuid4())
    now = utc_now()
    hashed = password_hash.hash(payload.password)
    try:
        with connect() as db:
            db.execute("INSERT INTO auth_users(id,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                       (user_id, email, hashed, payload.role, now))
            if payload.role == "seller":
                db.execute("INSERT INTO seller_accounts(id,user_id,created_at) VALUES(?,?,?)", (str(uuid4()), user_id, now))
    except Exception as error:
        if "UNIQUE constraint failed: auth_users.email" in str(error):
            raise HTTPException(status_code=409, detail="An account with this email already exists") from error
        raise
    return _set_session(response, request, {"id": user_id, "email": email, "role": payload.role,
                                             "seller_id": None})


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    connect, _ = _db_helpers()
    email = payload.email.strip().casefold()
    _check_auth_origin(request)
    with connect() as db:
        row = db.execute("SELECT * FROM auth_users WHERE email=?", (email,)).fetchone()
        seller = db.execute("SELECT id FROM seller_accounts WHERE user_id=?", (row["id"],)).fetchone() if row else None
    if row is None or not password_hash.verify(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return _set_session(response, request, {"id": row["id"], "email": row["email"], "role": row["role"],
                                             "seller_id": seller["id"] if seller else None})


@router.get("/me")
def me(request: Request):
    return authenticate_request(request, require_csrf=False)


@router.post("/logout")
def logout(request: Request, response: Response):
    connect, utc_now = _db_helpers()
    user = authenticate_request(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    with connect() as db:
        db.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND user_id=? AND revoked_at IS NULL",
                   (utc_now(), _token_digest(token), user["id"]))
    options = _cookie_options(request)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=options["secure"], httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=options["secure"], samesite="strict")
    return {"logged_out": True}


def seller_grants_for_passport(db, passport_id: str, seller_id: str) -> bool:
    _, utc_now = _db_helpers()
    return db.execute("""SELECT 1 FROM passport_seller_grants WHERE passport_id=? AND seller_id=?
        AND status='accepted' AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)""",
        (passport_id, seller_id, utc_now())).fetchone() is not None


def _check_auth_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    allowed = {item.strip().rstrip("/") for item in os.getenv("MIRROR_CORS_ORIGINS", "http://127.0.0.1:5501").split(",")}
    if origin and origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")

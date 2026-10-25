"""Signed, expiring session tokens and demo credential verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

TOKEN_LIFETIME_SECONDS = 12 * 60 * 60
TOKEN_SECRET = os.getenv("CASHFLOW_AUTH_SECRET") or base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
PASSWORD_HASH_ITERATIONS = 310_000
DEMO_INN_ORDINALS = {"7701001001": 0, "7701002002": 1}


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(user: dict[str, object]) -> str:
    """Create an HMAC-SHA256 signed token with a fixed expiration time."""
    payload = {**user, "exp": int(time.time()) + TOKEN_LIFETIME_SECONDS}
    encoded_payload = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(TOKEN_SECRET.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_encode(signature)}"


def verify_session_token(token: str) -> dict[str, object] | None:
    """Return claims only when signature, role and expiration are valid."""
    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        expected = hmac.new(TOKEN_SECRET.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(encoded_signature)):
            return None
        payload = json.loads(_decode(encoded_payload))
        if not isinstance(payload, dict) or payload.get("role") not in {"admin", "owner", "company"}:
            return None
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= int(time.time()):
            return None
        if not isinstance(payload.get("display_name"), str):
            return None
        if payload["role"] in {"owner", "company"} and not isinstance(payload.get("company_id"), str):
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return f"pbkdf2_sha256${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$", maxsplit=2)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _decode(salt), PASSWORD_HASH_ITERATIONS,
        )
        return hmac.compare_digest(digest, _decode(expected))
    except (ValueError, TypeError):
        return False


def authenticate_user(dataset, username: str, password: str, store=None) -> dict[str, object] | None:
    """Authenticate the demo admin or a company ID/INN against loaded companies."""
    login = username.strip()
    if login.casefold() == "admin" and password.casefold() == "admin":
        return {"role": "admin", "company_id": None, "display_name": "Администратор", "inn": None}

    companies = dataset.companies
    if not login or companies.empty:
        return None
    if store is not None:
        registered = store.get_user(login)
        if registered is not None:
            if not verify_password(password, registered["password"]):
                return None
            return {
                "role": "owner" if registered["role"] == "company" else registered["role"],
                "company_id": registered["company_id"],
                "display_name": registered["company_name"],
                "inn": registered["inn"],
            }
    company_ids = companies["company_id"].fillna("").astype(str).str.strip()
    inns = companies["inn"].fillna("").astype(str).str.strip()
    matches = companies.loc[
        company_ids.str.casefold().eq(login.casefold()) | inns.str.casefold().eq(login.casefold())
    ]
    demo_ordinal = DEMO_INN_ORDINALS.get(login)
    if matches.empty and demo_ordinal is not None and demo_ordinal < len(companies):
        matches = companies.sort_values("company_id", kind="stable").iloc[[demo_ordinal]]
    if matches.empty or not (password == "1234" or password.casefold() == login.casefold()):
        return None
    company = matches.iloc[0]
    return {
        "role": "owner",
        "company_id": str(company["company_id"]),
        "display_name": str(company["name"]),
        "inn": login if demo_ordinal is not None and inns.eq(login).sum() == 0 else str(company["inn"]),
    }
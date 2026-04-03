import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta

import jwt

JWT_ALGORITHM = "HS256"
JWT_ACCESS_TYP = "access"


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured.")
    return secret


def ensure_jwt_secret_configured() -> None:
    """Raises RuntimeError when JWT_SECRET is missing."""
    _jwt_secret()


def access_token_ttl() -> timedelta:
    minutes = int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", "15"))
    return timedelta(minutes=minutes)


def refresh_token_ttl() -> timedelta:
    days = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "30"))
    return timedelta(days=days)


def create_access_token(user_id: str, *, now: datetime | None = None) -> tuple[str, int]:
    issued = now or datetime.now(UTC)
    ttl = access_token_ttl()
    expires = issued + ttl
    payload = {
        "sub": user_id,
        "typ": JWT_ACCESS_TYP,
        "iat": issued,
        "exp": expires,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    expires_in = int(ttl.total_seconds())
    return token, expires_in


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    if payload.get("typ") != JWT_ACCESS_TYP:
        raise jwt.InvalidTokenError("Not an access token.")
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise jwt.InvalidTokenError("Missing subject.")
    return sub


def new_refresh_token_value() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

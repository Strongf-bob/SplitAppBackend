import os

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

from app.core import tokens

AUTH_TOKEN_ENV_KEY = "AUTH_TOKEN"

UNAUTHENTICATED_PATHS = frozenset(
    {
        "/api/ping",
        "/api/login",
        "/api/refresh",
    }
)

bearer_scheme = HTTPBearer(auto_error=False)


def _is_unauthenticated_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    exempt = {p.rstrip("/") for p in UNAUTHENTICATED_PATHS}
    return normalized in exempt


def get_db(request: Request) -> Database:
    return request.app.state.db


def require_auth_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    if _is_unauthenticated_path(request.url.path):
        return

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw = credentials.credentials
    legacy = os.getenv(AUTH_TOKEN_ENV_KEY, "").strip()
    if legacy and raw == legacy:
        request.state.auth_legacy = True
        request.state.user_id = None
        return

    try:
        tokens.ensure_jwt_secret_configured()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured.",
        )

    request.state.auth_legacy = False
    try:
        request.state.user_id = tokens.decode_access_token(raw)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_actor_user_id(request: Request) -> str | None:
    """JWT subject user id, or None when the legacy AUTH_TOKEN was used."""
    if getattr(request.state, "auth_legacy", False):
        return None
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


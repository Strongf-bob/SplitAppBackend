from typing import Any
from ipaddress import ip_address
import logging

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

from app.core import tokens
from app.core.s3 import get_s3_client

logger = logging.getLogger("splitapp")

INTERNAL_OPERATIONS_PATHS = frozenset(
    {
        "/api/health/db",
        "/api/metrics",
    }
)
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


def _is_internal_operations_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    exempt = {p.rstrip("/") for p in INTERNAL_OPERATIONS_PATHS}
    return normalized in exempt


def _is_internal_client(host: str | None) -> bool:
    if host == "testclient":
        return True
    if not host:
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_s3(request: Request) -> Any:
    return get_s3_client(request.app)


def require_auth_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    if _is_internal_operations_path(request.url.path):
        if request.client and _is_internal_client(request.client.host):
            return
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    if _is_unauthenticated_path(request.url.path):
        return

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw = credentials.credentials

    try:
        tokens.ensure_jwt_secret_configured()
    except RuntimeError:
        logger.error("JWT_SECRET is not configured.", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error.",
        )

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


def get_actor_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id

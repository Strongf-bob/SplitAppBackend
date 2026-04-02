import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

AUTH_TOKEN_ENV_KEY = "AUTH_TOKEN"

bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Database:
    return request.app.state.db


def require_auth_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    auth_token = os.getenv(AUTH_TOKEN_ENV_KEY, "").strip()
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{AUTH_TOKEN_ENV_KEY} is not configured.",
        )

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid auth token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pymongo.database import Database

from app import schemas, services
from app.core.rate_limit import check_rate_limit
from app.dependencies import get_db, get_s3

router = APIRouter(tags=["Auth"])


@router.post("/api/login", response_model=schemas.LoginResponse, status_code=status.HTTP_200_OK)
def login(
    payload: schemas.LoginYandexRequest,
    request: Request,
    db: Database = Depends(get_db),
    s3: Any = Depends(get_s3),
) -> dict:
    check_rate_limit("auth.login", request.client.host if request.client else "unknown")
    return services.login_with_yandex_oauth(db, payload.yandex_token, s3=s3)


@router.post("/api/refresh", response_model=schemas.RefreshResponse, status_code=status.HTTP_200_OK)
def refresh_tokens(
    payload: schemas.RefreshRequest,
    request: Request,
    db: Database = Depends(get_db),
) -> dict:
    check_rate_limit("auth.refresh", request.client.host if request.client else "unknown")
    return services.rotate_refresh_token(db, payload.refresh_token)

from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_db

router = APIRouter(tags=["Auth"])


@router.post("/api/login", response_model=schemas.LoginResponse, status_code=status.HTTP_200_OK)
def login(payload: schemas.LoginYandexRequest, db: Database = Depends(get_db)) -> dict:
    return services.login_with_yandex_oauth(db, payload.yandex_token)


@router.post("/api/refresh", response_model=schemas.RefreshResponse, status_code=status.HTTP_200_OK)
def refresh_tokens(payload: schemas.RefreshRequest, db: Database = Depends(get_db)) -> dict:
    return services.rotate_refresh_token(db, payload.refresh_token)

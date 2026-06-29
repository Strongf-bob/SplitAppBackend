from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Users"])


@router.get("/api/users", response_model=schemas.UserPage)
def list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_users(db, current_user_id, limit=limit, offset=offset)


@router.patch("/api/users/me", response_model=schemas.User)
def update_current_user(
    payload: schemas.UserUpdate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.update_current_user(db, current_user_id, payload)

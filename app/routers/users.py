from fastapi import APIRouter, Depends
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Users"])


@router.get("/api/users", response_model=list[schemas.User])
def list_users(
    db: Database = Depends(get_db),
    _current_user_id: str = Depends(get_actor_user_id),
) -> list[dict]:
    return services.list_users(db)


@router.patch("/api/users/me", response_model=schemas.User)
def update_current_user(
    payload: schemas.UserUpdate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.update_current_user(db, current_user_id, payload)

from fastapi import APIRouter, Depends
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Users"])


@router.get("/api/users", response_model=list[schemas.User])
def list_users(
    db: Database = Depends(get_db),
    _current_user_id: str | None = Depends(get_actor_user_id),
) -> list[dict]:
    return services.list_users(db)

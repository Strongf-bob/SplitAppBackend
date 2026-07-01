from fastapi import APIRouter, Depends
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Home"])


@router.get("/api/home/summary", response_model=schemas.HomeSummary)
def get_home_summary(
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.get_home_summary(db, current_user_id)

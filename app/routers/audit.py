from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Audit"])


@router.get("/api/events/{id}/activity", response_model=schemas.AuditEventPage)
def list_event_activity(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_event_activity(db, str(id), current_user_id, limit=limit, offset=offset)

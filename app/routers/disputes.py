from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Disputes"])


@router.post("/api/disputes", response_model=schemas.Dispute, status_code=201)
def create_dispute(
    payload: schemas.DisputeCreate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_dispute(db, payload, current_user_id)


@router.get("/api/events/{id}/disputes", response_model=schemas.DisputePage)
def list_event_disputes(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_event_disputes(db, str(id), current_user_id, limit=limit, offset=offset)


@router.post("/api/disputes/{id}/resolve", response_model=schemas.Dispute)
def resolve_dispute(
    id: UUID,
    payload: schemas.DisputeResolve,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.resolve_dispute(db, str(id), payload, current_user_id)

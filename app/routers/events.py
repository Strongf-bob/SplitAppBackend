from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_db

router = APIRouter(tags=["Events"])


@router.post("/api/events", response_model=schemas.Event, status_code=status.HTTP_201_CREATED)
def create_event(payload: schemas.EventCreate, db: Database = Depends(get_db)) -> dict:
    return services.create_event(db, payload)


@router.get("/api/events", response_model=list[schemas.Event])
def list_events(user_id: UUID | None = None, db: Database = Depends(get_db)) -> list[dict]:
    user_id_str = str(user_id) if user_id else None
    return services.list_events(db, user_id_str)


@router.get("/api/events/{id}", response_model=schemas.Event)
def get_event(id: UUID, db: Database = Depends(get_db)) -> dict:
    return services.get_event(db, str(id))


@router.patch("/api/events/{id}", response_model=schemas.Event)
def update_event(
    id: UUID,
    payload: schemas.EventUpdate,
    db: Database = Depends(get_db),
) -> dict:
    return services.update_event(db, str(id), payload)


@router.post(
    "/api/events/{id}/participants",
    response_model=list[schemas.User],
    status_code=status.HTTP_201_CREATED,
)
def add_event_participants(
    id: UUID,
    payload: schemas.AddParticipantsRequest,
    db: Database = Depends(get_db),
) -> list[dict]:
    return services.add_participants(db, str(id), payload)


@router.delete("/api/events/{id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_event_participant(
    id: UUID,
    user_id: UUID,
    db: Database = Depends(get_db),
) -> Response:
    services.remove_participant(db, str(id), str(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/events/{id}/balances", response_model=list[schemas.EventBalance])
def get_event_balances(id: UUID, db: Database = Depends(get_db)) -> list[dict]:
    return services.get_event_balances(db, str(id))


from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Events"])


@router.post("/api/events", response_model=schemas.Event, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: schemas.EventCreate,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> dict:
    return services.create_event(db, payload, current_user_id)


@router.get("/api/events", response_model=list[schemas.Event])
def list_events(
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> list[dict]:
    return services.list_events(db, current_user_id)


@router.get("/api/events/{id}", response_model=schemas.Event)
def get_event(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> dict:
    return services.get_event(db, str(id), current_user_id)


@router.patch("/api/events/{id}", response_model=schemas.Event)
def update_event(
    id: UUID,
    payload: schemas.EventUpdate,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> dict:
    return services.update_event(db, str(id), payload, current_user_id)


@router.post(
    "/api/events/{id}/participants",
    response_model=list[schemas.User],
    status_code=status.HTTP_201_CREATED,
)
def add_event_participants(
    id: UUID,
    payload: schemas.AddParticipantsRequest,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> list[dict]:
    return services.add_participants(db, str(id), payload, current_user_id)


@router.delete("/api/events/{id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_event_participant(
    id: UUID,
    user_id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> Response:
    services.remove_participant(db, str(id), str(user_id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/events/{id}/balances", response_model=list[schemas.EventBalance])
def get_event_balances(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> list[dict]:
    return services.get_event_balances(db, str(id), current_user_id)


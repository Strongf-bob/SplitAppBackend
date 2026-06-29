from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Events"])


@router.post("/api/events", response_model=schemas.Event, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: schemas.EventCreate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_event(db, payload, current_user_id)


@router.get("/api/events", response_model=schemas.EventPage)
def list_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_events(db, current_user_id, limit=limit, offset=offset)


@router.get("/api/events/{id}", response_model=schemas.Event)
def get_event(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.get_event(db, str(id), current_user_id)


@router.patch("/api/events/{id}", response_model=schemas.Event)
def update_event(
    id: UUID,
    payload: schemas.EventUpdate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.update_event(db, str(id), payload, current_user_id)


@router.delete("/api/events/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.delete_event(db, str(id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/events/{id}/participants",
    response_model=list[schemas.User],
    status_code=status.HTTP_201_CREATED,
)
def add_event_participants(
    id: UUID,
    payload: schemas.AddParticipantsRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> list[dict]:
    return services.add_participants(db, str(id), payload, current_user_id)


@router.delete("/api/events/{id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_event_participant(
    id: UUID,
    user_id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.remove_participant(db, str(id), str(user_id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/events/{id}/invites",
    response_model=schemas.EventInvite,
    status_code=status.HTTP_201_CREATED,
)
def create_event_invite(
    id: UUID,
    payload: schemas.CreateEventInviteRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_event_invite(db, str(id), payload, current_user_id)


@router.get("/api/invites/{token}/preview", response_model=schemas.EventInvitePreview)
def preview_event_invite(
    token: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.preview_event_invite(db, token, current_user_id)


@router.post("/api/invites/{token}/accept", response_model=schemas.Event)
def accept_event_invite(
    token: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.accept_event_invite(db, token, current_user_id)


@router.delete(
    "/api/events/{id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_event_invite(
    id: UUID,
    invite_id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.revoke_event_invite(db, str(id), str(invite_id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/events/{id}/nearby-code",
    response_model=schemas.NearbyInviteCode,
    status_code=status.HTTP_201_CREATED,
)
def create_nearby_invite_code(
    id: UUID,
    payload: schemas.CreateNearbyInviteCodeRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_nearby_invite_code(db, str(id), payload, current_user_id)


@router.get("/api/nearby-invites/{code}/preview", response_model=schemas.EventInvitePreview)
def preview_nearby_invite_code(
    code: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.preview_nearby_invite_code(db, code, current_user_id)


@router.post("/api/nearby-invites/{code}/accept", response_model=schemas.Event)
def accept_nearby_invite_code(
    code: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.accept_nearby_invite_code(db, code, current_user_id)


@router.get("/api/events/{id}/balances", response_model=list[schemas.EventBalance])
def get_event_balances(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> list[dict]:
    return services.get_event_balances(db, str(id), current_user_id)


@router.get(
    "/api/events/{id}/balances/explain",
    response_model=list[schemas.EventBalanceExplanation],
)
def get_event_balance_explanations(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> list[dict]:
    return services.get_event_balance_explanations(db, str(id), current_user_id)

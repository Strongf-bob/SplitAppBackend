from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
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


@router.get(
    "/api/events/{id}/close/confirmation-summary", response_model=schemas.ConfirmationSummary
)
def get_event_close_confirmation_summary(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.get_event_close_confirmation_summary(db, str(id), current_user_id)


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


@router.post("/api/invites/{token}/decline", response_model=schemas.EventInvitePreview)
def decline_event_invite(
    token: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.decline_event_invite(db, token, current_user_id)


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


@router.get("/api/events/{id}/settlement-preview", response_model=schemas.SettlementPreview)
def get_event_settlement_preview(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.get_settlement_preview(db, str(id), current_user_id)


@router.post(
    "/api/events/{id}/settlement-plans",
    response_model=schemas.SettlementPlan,
    status_code=status.HTTP_201_CREATED,
)
def create_settlement_plan(
    id: UUID,
    idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_settlement_plan(
        db, str(id), current_user_id, idempotency_key=idempotency_key
    )


@router.get("/api/events/{id}/settlement-plans", response_model=schemas.SettlementPlanPage)
def list_settlement_plans(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_settlement_plans(db, str(id), current_user_id, limit=limit, offset=offset)


@router.get("/api/settlement-plans/{id}", response_model=schemas.SettlementPlan)
def get_settlement_plan(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.get_settlement_plan(db, str(id), current_user_id)


@router.post("/api/settlement-plans/{id}/approve", response_model=schemas.SettlementPlan)
def approve_settlement_plan(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.approve_settlement_plan(db, str(id), current_user_id)


@router.post("/api/settlement-plans/{id}/reject", response_model=schemas.SettlementPlan)
def reject_settlement_plan(
    id: UUID,
    payload: schemas.SettlementPlanReject,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.reject_settlement_plan(db, str(id), current_user_id, payload.reason)

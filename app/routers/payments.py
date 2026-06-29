from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Payments"])


@router.post(
    "/api/events/{id}/payments",
    response_model=schemas.Payment,
    status_code=status.HTTP_201_CREATED,
)
def create_payment(
    id: UUID,
    payload: schemas.PaymentCreate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_payment(db, str(id), payload, current_user_id)


@router.get("/api/events/{id}/payments", response_model=schemas.PaymentPage)
def list_payments_by_event(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_payments_by_event(
        db, str(id), current_user_id, limit=limit, offset=offset
    )


@router.patch("/api/payments/{id}", response_model=schemas.Payment)
def update_payment(
    id: UUID,
    payload: schemas.PaymentUpdate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.update_payment(db, str(id), payload, current_user_id)


@router.delete("/api/payments/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.delete_payment(db, str(id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

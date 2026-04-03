from uuid import UUID

from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_current_user_id, get_db

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
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    return services.create_payment(db, str(id), payload, current_user_id)


@router.get("/api/events/{id}/payments", response_model=list[schemas.Payment])
def list_payments_by_event(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    return services.list_payments_by_event(db, str(id), current_user_id)


@router.patch("/api/payments/{id}", response_model=schemas.Payment)
def update_payment(
    id: UUID,
    payload: schemas.PaymentUpdate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    return services.update_payment(db, str(id), payload, current_user_id)


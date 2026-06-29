from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
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
    idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_payment(
        db, str(id), payload, current_user_id, idempotency_key=idempotency_key
    )


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


@router.post(
    "/api/events/{id}/payment-requests",
    response_model=schemas.PaymentRequest,
    status_code=status.HTTP_201_CREATED,
)
def create_payment_request(
    id: UUID,
    payload: schemas.PaymentRequestCreate,
    idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_payment_request(
        db, str(id), payload, current_user_id, idempotency_key=idempotency_key
    )


@router.get("/api/events/{id}/payment-requests", response_model=schemas.PaymentRequestPage)
def list_payment_requests_by_event(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_payment_requests_by_event(
        db, str(id), current_user_id, limit=limit, offset=offset
    )


@router.post("/api/payment-requests/{id}/mark-paid", response_model=schemas.Payment)
def mark_payment_request_paid(
    id: UUID,
    idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.mark_payment_request_paid(
        db, str(id), current_user_id, idempotency_key=idempotency_key
    )


@router.post("/api/payment-requests/{id}/acknowledge", response_model=schemas.PaymentRequest)
def acknowledge_payment_request(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.acknowledge_payment_request(db, str(id), current_user_id)


@router.post("/api/payment-requests/{id}/cancel", response_model=schemas.PaymentRequest)
def cancel_payment_request(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.cancel_payment_request(db, str(id), current_user_id)


@router.post("/api/payment-requests/{id}/request-extension", response_model=schemas.PaymentRequest)
def request_payment_extension(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.request_payment_extension(db, str(id), current_user_id)


@router.post("/api/payment-requests/{id}/dispute", response_model=schemas.PaymentRequest)
def dispute_payment_request(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.dispute_payment_request(db, str(id), current_user_id)


@router.post("/api/payments/{id}/confirm", response_model=schemas.Payment)
def confirm_payment(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.confirm_payment(db, str(id), current_user_id)


@router.post("/api/payments/{id}/reject", response_model=schemas.Payment)
def reject_payment(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.reject_payment(db, str(id), current_user_id)


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

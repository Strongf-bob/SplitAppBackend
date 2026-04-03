from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["Receipts"])


@router.post(
    "/api/events/{id}/receipts",
    response_model=schemas.Receipt,
    status_code=status.HTTP_201_CREATED,
)
def create_receipt(
    id: UUID,
    payload: schemas.CreateReceiptRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    return services.create_receipt(db, str(id), payload, current_user_id)


@router.get("/api/events/{id}/receipts", response_model=list[schemas.Receipt])
def list_receipts_by_event(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    return services.list_receipts_by_event(db, str(id), current_user_id)


@router.patch("/api/receipts/{id}", response_model=schemas.Receipt)
def update_receipt(
    id: UUID,
    payload: schemas.UpdateReceiptRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    return services.update_receipt(db, str(id), payload, current_user_id)


@router.delete("/api/receipts/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
) -> Response:
    services.delete_receipt(db, str(id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


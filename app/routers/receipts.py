from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_db

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
) -> dict:
    return services.create_receipt(db, str(id), payload)


@router.get("/api/events/{id}/receipts", response_model=list[schemas.Receipt])
def list_receipts_by_event(id: UUID, db: Database = Depends(get_db)) -> list[dict]:
    return services.list_receipts_by_event(db, str(id))


@router.patch("/api/receipts/{id}", response_model=schemas.Receipt)
def update_receipt(
    id: UUID,
    payload: schemas.UpdateReceiptRequest,
    db: Database = Depends(get_db),
) -> dict:
    return services.update_receipt(db, str(id), payload)


@router.delete("/api/receipts/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(id: UUID, db: Database = Depends(get_db)) -> Response:
    services.delete_receipt(db, str(id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


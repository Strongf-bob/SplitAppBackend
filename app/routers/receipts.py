from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db, get_s3

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
    current_user_id: str | None = Depends(get_actor_user_id),
) -> dict:
    return services.create_receipt(db, str(id), payload, current_user_id)


@router.get("/api/events/{id}/receipts", response_model=list[schemas.Receipt])
def list_receipts_by_event(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> list[dict]:
    return services.list_receipts_by_event(db, str(id), current_user_id)


@router.patch("/api/receipts/{id}", response_model=schemas.Receipt)
def update_receipt(
    id: UUID,
    payload: schemas.UpdateReceiptRequest,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> dict:
    return services.update_receipt(db, str(id), payload, current_user_id)


@router.delete("/api/receipts/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str | None = Depends(get_actor_user_id),
) -> Response:
    services.delete_receipt(db, str(id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/receipts/{id}/image",
    response_model=schemas.ReceiptImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_receipt_image(
    id: UUID,
    db: Database = Depends(get_db),
    s3=Depends(get_s3),
    current_user_id: str | None = Depends(get_actor_user_id),
    file: UploadFile | None = File(
        None,
        description="JPEG image (.jpg or .jpeg); use this field or `image`.",
    ),
    image: UploadFile | None = File(
        None,
        description="Same as `file` (alternate form field name some clients use).",
    ),
) -> dict[str, str]:
    upload = file or image
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="Send the JPEG as multipart form-data with field name 'file' or 'image'.",
        )
    body = await upload.read()
    return services.upload_receipt_image(
        db, s3, str(id), body, upload.content_type, current_user_id
    )


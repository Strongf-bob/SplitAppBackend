from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
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
    idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_receipt(
        db, str(id), payload, current_user_id, idempotency_key=idempotency_key
    )


@router.get("/api/events/{id}/receipts", response_model=schemas.ReceiptPage)
def list_receipts_by_event(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_receipts_by_event(
        db, str(id), current_user_id, limit=limit, offset=offset
    )


@router.get("/api/receipts/{id}", response_model=schemas.Receipt)
def get_receipt(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.get_receipt(db, str(id), current_user_id)


@router.patch("/api/receipts/{id}", response_model=schemas.Receipt)
def update_receipt(
    id: UUID,
    payload: schemas.UpdateReceiptRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.update_receipt(db, str(id), payload, current_user_id)


@router.delete("/api/receipts/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
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
    current_user_id: str = Depends(get_actor_user_id),
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


@router.delete("/api/receipts/{id}/image", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt_image(
    id: UUID,
    db: Database = Depends(get_db),
    s3=Depends(get_s3),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.delete_receipt_image(db, s3, str(id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/receipts/{id}/image/presigned-url",
    response_model=schemas.ReceiptImagePresignedUrlResponse,
)
def get_receipt_image_presigned_url(
    id: UUID,
    db: Database = Depends(get_db),
    s3=Depends(get_s3),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict[str, str]:
    return services.get_receipt_image_presigned_url(db, s3, str(id), current_user_id)

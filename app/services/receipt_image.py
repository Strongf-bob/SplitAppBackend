import os
from typing import Any

from fastapi import HTTPException
from pymongo.database import Database

from app.services.access import assert_event_access, get_receipt_or_404
from app.services.common import new_uuid, utc_now

_JPEG_MAGIC = b"\xff\xd8\xff"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _bucket_name() -> str | None:
    name = os.getenv("S3_BUCKET", "").strip()
    return name or None


def public_url_for_object(bucket: str, key: str) -> str:
    endpoint = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net").strip().rstrip("/")
    return f"{endpoint}/{bucket}/{key}"


def upload_receipt_image(
    db: Database,
    s3: Any,
    receipt_id: str,
    body: bytes,
    content_type: str | None,
    actor_user_id: str | None,
) -> dict[str, str]:
    receipt = get_receipt_or_404(db, receipt_id)
    assert_event_access(db, receipt["event_id"], actor_user_id)

    if len(body) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB).")

    if len(body) < 3 or not body.startswith(_JPEG_MAGIC):
        raise HTTPException(status_code=400, detail="File must be a JPEG image.")

    if content_type:
        ct = content_type.lower()
        if ct.startswith("image/") and "jpeg" not in ct and "jpg" not in ct:
            raise HTTPException(status_code=400, detail="File must be a JPEG image.")

    bucket = _bucket_name()
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured (S3_BUCKET).",
        )

    key = f"receipts/{receipt_id}/{new_uuid()}.jpg"
    image_url = public_url_for_object(bucket, key)

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="image/jpeg",
        ACL="public-read",
    )

    now = utc_now()
    db.receipts.update_one(
        {"id": receipt_id},
        {"$set": {"image_url": image_url, "updated_at": now}},
    )

    return {"image_url": image_url}

import os
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import HTTPException
from pymongo.database import Database

from app.core.monitoring import track_service_operation
from app.services.access import assert_event_access, assert_event_open, get_receipt_or_404
from app.services.common import new_uuid, utc_now

_JPEG_MAGIC = b"\xff\xd8\xff"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _bucket_name() -> str | None:
    name = os.getenv("S3_BUCKET", "").strip()
    return name or None


def public_url_for_object(bucket: str, key: str) -> str:
    endpoint = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net").strip().rstrip("/")
    return f"{endpoint}/{bucket}/{key}"


def _object_key_from_url(bucket: str, image_url: str | None) -> str | None:
    if not image_url:
        return None
    parsed = urlparse(image_url)
    path = unquote(parsed.path).lstrip("/")
    prefix = f"{bucket}/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return None


def _receipt_image_key(receipt: dict, bucket: str) -> str | None:
    return receipt.get("image_key") or _object_key_from_url(bucket, receipt.get("image_url"))


@track_service_operation("receipt_images.upload")
def upload_receipt_image(
    db: Database,
    s3: Any,
    receipt_id: str,
    body: bytes,
    content_type: str | None,
    actor_user_id: str,
) -> dict[str, str]:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)

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
    old_key = _receipt_image_key(receipt, bucket)

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="image/jpeg",
    )
    if old_key and old_key != key:
        s3.delete_object(Bucket=bucket, Key=old_key)

    now = utc_now()
    db.receipts.update_one(
        {"id": receipt_id},
        {"$set": {"image_url": image_url, "image_key": key, "updated_at": now}},
    )

    return {"image_url": image_url}


@track_service_operation("receipt_images.delete")
def delete_receipt_image(db: Database, s3: Any, receipt_id: str, actor_user_id: str) -> None:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)

    bucket = _bucket_name()
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured (S3_BUCKET).",
        )

    key = _receipt_image_key(receipt, bucket)
    if not key:
        raise HTTPException(status_code=404, detail="Receipt image not found.")

    s3.delete_object(Bucket=bucket, Key=key)
    db.receipts.update_one(
        {"id": receipt_id},
        {"$unset": {"image_url": "", "image_key": ""}, "$set": {"updated_at": utc_now()}},
    )


@track_service_operation("receipt_images.presign")
def get_receipt_image_presigned_url(
    db: Database,
    s3: Any,
    receipt_id: str,
    actor_user_id: str,
) -> dict[str, str]:
    receipt = get_receipt_or_404(db, receipt_id)
    assert_event_access(db, receipt["event_id"], actor_user_id)

    bucket = _bucket_name()
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured (S3_BUCKET).",
        )

    key = _receipt_image_key(receipt, bucket)
    if not key:
        if receipt.get("image_url"):
            return {"image_url": receipt["image_url"]}
        raise HTTPException(status_code=404, detail="Receipt image not found.")

    return {
        "image_url": s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=900,
        )
    }

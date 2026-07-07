import os
from typing import Any

from fastapi import HTTPException
from pymongo.database import Database

from app.services.common import new_uuid, strip_mongo_id, utc_now

_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def _bucket_name() -> str | None:
    bucket = os.getenv("S3_BUCKET", "").strip()
    return bucket or None


def _public_metadata(attachment: dict) -> dict:
    cleaned = strip_mongo_id(attachment)
    cleaned.pop("bucket", None)
    cleaned.pop("key", None)
    cleaned.pop("content", None)
    return cleaned


def create_attachment(
    db: Database,
    s3: Any,
    *,
    actor_user_id: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> dict:
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Attachment too large (max 10 MB).")
    normalized_content_type = content_type.strip().lower()
    if normalized_content_type not in _IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Attachment must be an image.")
    attachment_id = new_uuid()
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    now = utc_now()
    attachment = {
        "id": attachment_id,
        "owner_user_id": actor_user_id,
        "filename": filename,
        "content_type": normalized_content_type,
        "size_bytes": len(content),
        "created_at": now,
    }
    bucket = _bucket_name()
    if bucket:
        key = f"attachments/splitik/{actor_user_id}/{attachment_id}.{extension}"
        s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=normalized_content_type)
        attachment.update({"storage": "s3", "bucket": bucket, "key": key})
    else:
        attachment.update({"storage": "mongo", "content": content})
    db.splitik_attachments.insert_one(attachment)
    return _public_metadata(attachment)


def list_attachments_for_actor(
    db: Database,
    *,
    actor_user_id: str,
    attachment_ids: list[str],
) -> list[dict]:
    if not attachment_ids:
        return []
    attachments = list(
        db.splitik_attachments.find({"id": {"$in": attachment_ids}, "owner_user_id": actor_user_id})
    )
    if len(attachments) != len(set(attachment_ids)):
        raise HTTPException(status_code=404, detail="Splitik attachment not found.")
    return [_public_metadata(attachment) for attachment in attachments]

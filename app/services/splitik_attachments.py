import os
from typing import Any

from fastapi import HTTPException
from pymongo.database import Database

from app.core.rate_limit import check_rate_limit
from app.services.common import new_uuid, strip_mongo_id, utc_now

_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
_IMAGE_MAGIC_PREFIXES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/jpg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


def _bucket_name() -> str | None:
    bucket = os.getenv("S3_BUCKET", "").strip()
    return bucket or None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _public_metadata(attachment: dict) -> dict:
    cleaned = strip_mongo_id(attachment)
    cleaned.pop("bucket", None)
    cleaned.pop("key", None)
    cleaned.pop("content", None)
    return cleaned


def _content_matches_type(content_type: str, content: bytes) -> bool:
    prefixes = _IMAGE_MAGIC_PREFIXES.get(content_type, ())
    if content_type == "image/webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return any(content.startswith(prefix) for prefix in prefixes)


def create_attachment(
    db: Database,
    s3: Any,
    *,
    actor_user_id: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> dict:
    check_rate_limit(
        "splitik.attachments.day",
        actor_user_id,
        max_requests=_env_int("SPLITIK_ATTACHMENT_DAILY_LIMIT", 10),
        window_seconds=24 * 60 * 60,
        detail="Splitik attachment daily limit exceeded.",
    )
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Attachment too large (max 10 MB).")
    normalized_content_type = content_type.strip().lower()
    if normalized_content_type not in _IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Attachment must be an image.")
    if not _content_matches_type(normalized_content_type, content):
        raise HTTPException(status_code=400, detail="Attachment content does not match image type.")
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


def read_attachments_for_actor(
    db: Database,
    s3: Any | None,
    *,
    actor_user_id: str,
    attachment_ids: list[str],
) -> list[tuple[dict, bytes]]:
    """Return private image bytes only for an authenticated model request."""
    if not attachment_ids:
        return []
    stored = list(
        db.splitik_attachments.find({"id": {"$in": attachment_ids}, "owner_user_id": actor_user_id})
    )
    by_id = {str(attachment["id"]): attachment for attachment in stored}
    if len(by_id) != len(set(attachment_ids)):
        raise HTTPException(status_code=404, detail="Splitik attachment not found.")

    result: list[tuple[dict, bytes]] = []
    for attachment_id in attachment_ids:
        attachment = by_id[attachment_id]
        if attachment.get("storage") == "s3":
            if s3 is None:
                raise HTTPException(
                    status_code=503, detail="Splitik attachment storage is unavailable."
                )
            try:
                content = s3.get_object(Bucket=attachment["bucket"], Key=attachment["key"])[
                    "Body"
                ].read()
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="Splitik attachment storage is unavailable."
                ) from exc
        else:
            content = attachment.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise HTTPException(
                status_code=503, detail="Splitik attachment storage is unavailable."
            )
        result.append((_public_metadata(attachment), bytes(content)))
    return result

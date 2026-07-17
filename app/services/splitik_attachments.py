import os
from threading import BoundedSemaphore
from typing import Any

from fastapi import HTTPException
from pymongo.database import Database

from app.core.rate_limit import check_rate_limit
from app.core.monitoring import record_receipt_image_preprocessing
from app.services.common import new_uuid, strip_mongo_id, utc_now
from app.services.receipt_image_preprocessing import (
    ReceiptImagePixelLimitError,
    preprocess_receipt_image,
)

_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_MAX_MONGO_ATTACHMENT_DOCUMENT_BYTES = 15 * 1024 * 1024
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


_PREPROCESSING_SLOTS = BoundedSemaphore(
    max(1, _env_int("SPLITIK_IMAGE_PREPROCESSING_CONCURRENT_LIMIT", 2))
)


def _public_metadata(attachment: dict) -> dict:
    cleaned = strip_mongo_id(attachment)
    cleaned.pop("bucket", None)
    cleaned.pop("key", None)
    cleaned.pop("content", None)
    cleaned.pop("derivative", None)
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
    try:
        with _PREPROCESSING_SLOTS:
            preprocessing = preprocess_receipt_image(content, normalized_content_type)
    except ReceiptImagePixelLimitError as exc:
        record_receipt_image_preprocessing(
            outcome="rejected",
            selected_variant="original",
            duration_seconds=0,
        )
        raise HTTPException(status_code=413, detail="Attachment dimensions are too large.") from exc
    attachment_id = new_uuid()
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    now = utc_now()
    attachment = {
        "id": attachment_id,
        "owner_user_id": actor_user_id,
        "filename": filename,
        "content_type": normalized_content_type,
        "size_bytes": len(content),
        "processing": preprocessing.metadata,
        "created_at": now,
    }
    bucket = _bucket_name()
    uploaded_objects: list[tuple[str, str]] = []
    if bucket:
        key = f"attachments/splitik/{actor_user_id}/{attachment_id}.{extension}"
        s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=normalized_content_type)
        uploaded_objects.append((bucket, key))
        attachment.update({"storage": "s3", "bucket": bucket, "key": key})
        if preprocessing.derivative_content is not None:
            derivative_content_type = preprocessing.derivative_content_type or "image/jpeg"
            derivative_extension = "png" if derivative_content_type == "image/png" else "jpg"
            derivative_key = (
                f"attachments/splitik/{actor_user_id}/{attachment_id}.model.{derivative_extension}"
            )
            try:
                s3.put_object(
                    Bucket=bucket,
                    Key=derivative_key,
                    Body=preprocessing.derivative_content,
                    ContentType=derivative_content_type,
                )
                uploaded_objects.append((bucket, derivative_key))
                attachment["derivative"] = {
                    "storage": "s3",
                    "bucket": bucket,
                    "key": derivative_key,
                    "content_type": derivative_content_type,
                    "size_bytes": len(preprocessing.derivative_content),
                }
            except Exception:
                attachment["processing"] = {
                    **preprocessing.metadata,
                    "status": "storage_failed",
                    "selected_variant": "original",
                }
    else:
        attachment.update({"storage": "mongo", "content": content})
        if preprocessing.derivative_content is not None:
            combined_size = len(content) + len(preprocessing.derivative_content)
            if combined_size <= _MAX_MONGO_ATTACHMENT_DOCUMENT_BYTES:
                attachment["derivative"] = {
                    "storage": "mongo",
                    "content": preprocessing.derivative_content,
                    "content_type": preprocessing.derivative_content_type or "image/jpeg",
                    "size_bytes": len(preprocessing.derivative_content),
                }
            else:
                attachment["processing"] = {
                    **preprocessing.metadata,
                    "status": "storage_failed",
                    "selected_variant": "original",
                }
    processing_metadata = attachment["processing"]
    try:
        db.splitik_attachments.insert_one(attachment)
    except Exception as exc:
        for uploaded_bucket, uploaded_key in reversed(uploaded_objects):
            try:
                s3.delete_object(Bucket=uploaded_bucket, Key=uploaded_key)
            except Exception:
                pass
        record_receipt_image_preprocessing(
            outcome="persistence_failed",
            selected_variant=str(processing_metadata["selected_variant"]),
            duration_seconds=float(processing_metadata.get("duration_ms") or 0) / 1000,
        )
        raise HTTPException(
            status_code=503, detail="Splitik attachment could not be stored."
        ) from exc
    else:
        record_receipt_image_preprocessing(
            outcome=str(processing_metadata["status"]),
            selected_variant=str(processing_metadata["selected_variant"]),
            duration_seconds=float(processing_metadata.get("duration_ms") or 0) / 1000,
        )
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


def image_urls_for_actor(
    db: Database,
    s3: Any | None,
    *,
    actor_user_id: str,
    attachment_ids: list[str],
) -> list[tuple[dict, str]]:
    """Return private image URLs only for an authenticated model request."""
    if not attachment_ids:
        return []
    stored = list(
        db.splitik_attachments.find({"id": {"$in": attachment_ids}, "owner_user_id": actor_user_id})
    )
    by_id = {str(attachment["id"]): attachment for attachment in stored}
    if len(by_id) != len(set(attachment_ids)):
        raise HTTPException(status_code=404, detail="Splitik attachment not found.")

    result: list[tuple[dict, str]] = []
    for attachment_id in attachment_ids:
        attachment = by_id[attachment_id]
        selected = attachment.get("derivative") or attachment
        if selected.get("storage") == "s3":
            if s3 is None:
                raise HTTPException(
                    status_code=503, detail="Splitik attachment storage is unavailable."
                )
            try:
                image_url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": selected["bucket"], "Key": selected["key"]},
                    ExpiresIn=900,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="Splitik attachment storage is unavailable."
                ) from exc
        else:
            image_url = ""
        if not image_url:
            raise HTTPException(
                status_code=503, detail="Splitik attachment storage is unavailable."
            )
        result.append((_public_metadata(attachment), image_url))
    return result


def delete_attachment(
    db: Database,
    s3: Any | None,
    *,
    actor_user_id: str,
    attachment_id: str,
) -> None:
    attachment = db.splitik_attachments.find_one(
        {"id": attachment_id, "owner_user_id": actor_user_id}
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="Splitik attachment not found.")

    def delete_s3_variant(variant: dict) -> None:
        if s3 is None:
            raise HTTPException(
                status_code=503, detail="Splitik attachment storage is unavailable."
            )
        try:
            s3.delete_object(Bucket=variant["bucket"], Key=variant["key"])
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Splitik attachment storage is unavailable."
            ) from exc

    derivative = attachment.get("derivative")
    if isinstance(derivative, dict) and derivative.get("storage") == "s3":
        delete_s3_variant(derivative)
        db.splitik_attachments.update_one(
            {"id": attachment_id, "owner_user_id": actor_user_id},
            {"$unset": {"derivative": ""}},
        )

    if attachment.get("storage") == "s3":
        delete_s3_variant(attachment)
    db.splitik_attachments.delete_one({"id": attachment_id, "owner_user_id": actor_user_id})

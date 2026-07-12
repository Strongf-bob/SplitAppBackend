import os
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from pymongo.database import Database

_MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _bucket_name() -> str | None:
    name = os.getenv("S3_BUCKET", "").strip()
    return name or None


def import_yandex_avatar(s3: Any, *, user_id: str, yandex_avatar_url: str | None) -> str | None:
    bucket = _bucket_name()
    if not bucket or not yandex_avatar_url:
        return None

    try:
        response = httpx.get(yandex_avatar_url, timeout=10.0, follow_redirects=True)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if (
            response.status_code != 200
            or not content_type.startswith("image/")
            or len(response.content) > _MAX_AVATAR_BYTES
        ):
            return None

        key = f"users/{user_id}/avatar.jpg"
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=response.content,
            ContentType=content_type,
        )
        return key
    except httpx.HTTPError:
        return None


def get_avatar_redirect(db: Database, s3: Any, user_id: str) -> RedirectResponse:
    user = db.users.find_one({"id": user_id})
    key = user.get("avatar_key") if user else None
    if not key:
        raise HTTPException(status_code=404, detail="Avatar not found.")

    bucket = _bucket_name()
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured (S3_BUCKET).",
        )

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=900,
    )
    return RedirectResponse(url=url, status_code=307)

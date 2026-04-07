from datetime import UTC

import httpx
from fastapi import HTTPException
from pymongo.database import Database

from app.core import tokens

from app.services.common import new_uuid, utc_now, user_to_api_dict

YANDEX_INFO_URL = "https://login.yandex.ru/info"


def _fetch_yandex_profile(oauth_token: str) -> dict:
    try:
        response = httpx.get(
            YANDEX_INFO_URL,
            headers={"Authorization": f"OAuth {oauth_token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not reach Yandex OAuth API.",
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Yandex OAuth token.",
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from Yandex OAuth API.",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Invalid JSON from Yandex OAuth API.",
        ) from exc

    yandex_id = data.get("id")
    if not yandex_id:
        raise HTTPException(
            status_code=502,
            detail="Yandex profile response missing id.",
        )

    return data


def _yandex_profile_to_fields(profile: dict) -> dict:
    yandex_id = str(profile["id"])
    display = (profile.get("display_name") or profile.get("login") or "").strip()
    real_name = (profile.get("real_name") or "").strip()
    name = display or real_name or yandex_id
    phone_obj = profile.get("default_phone") or {}
    phone = phone_obj.get("number") if isinstance(phone_obj, dict) else None
    phone_number = (phone or "").strip() or f"yandex:{yandex_id}"
    email_raw = profile.get("default_email")
    email = (str(email_raw).strip() if email_raw else "") or None
    avatar_raw = profile.get("default_avatar_id")
    default_avatar_id = (str(avatar_raw).strip() if avatar_raw else "") or None
    return {
        "yandex_id": yandex_id,
        "name": name,
        "phone_number": phone_number,
        "email": email,
        "default_avatar_id": default_avatar_id,
    }


def _issue_refresh_token(db: Database, user_id: str) -> str:
    now = utc_now()
    raw = tokens.new_refresh_token_value()
    token_hash = tokens.hash_refresh_token(raw)
    expires_at = now + tokens.refresh_token_ttl()
    db.refresh_tokens.insert_one(
        {
            "id": new_uuid(),
            "token_hash": token_hash,
            "user_id": user_id,
            "expires_at": expires_at,
            "created_at": now,
        }
    )
    return raw


def login_with_yandex_oauth(db: Database, oauth_token: str) -> dict:
    try:
        tokens.ensure_jwt_secret_configured()
    except RuntimeError:
        raise HTTPException(status_code=500, detail="JWT_SECRET is not configured.")

    profile = _fetch_yandex_profile(oauth_token)
    fields = _yandex_profile_to_fields(profile)
    yandex_id = fields["yandex_id"]
    now = utc_now()

    existing = db.users.find_one({"yandex_id": yandex_id})
    if existing:
        user_id = existing["id"]
        conflict = db.users.find_one(
            {"phone_number": fields["phone_number"], "id": {"$ne": user_id}}
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail="phone_number already in use by another account.",
            )
        db.users.update_one(
            {"id": user_id},
            {
                "$set": {
                    "name": fields["name"],
                    "phone_number": fields["phone_number"],
                    "email": fields["email"],
                    "default_avatar_id": fields["default_avatar_id"],
                    "updated_at": now,
                }
            },
        )
        user = db.users.find_one({"id": user_id})
    else:
        if db.users.find_one({"phone_number": fields["phone_number"]}):
            raise HTTPException(
                status_code=409,
                detail="phone_number already in use.",
            )
        user = {
            "id": new_uuid(),
            "yandex_id": yandex_id,
            "name": fields["name"],
            "phone_number": fields["phone_number"],
            "email": fields["email"],
            "default_avatar_id": fields["default_avatar_id"],
            "created_at": now,
            "updated_at": now,
        }
        db.users.insert_one(user)

    assert user is not None
    access_token, expires_in = tokens.create_access_token(user["id"])
    refresh_raw = _issue_refresh_token(db, user["id"])
    return {
        "user": user_to_api_dict(user),
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


def rotate_refresh_token(db: Database, raw_refresh: str) -> dict:
    try:
        tokens.ensure_jwt_secret_configured()
    except RuntimeError:
        raise HTTPException(status_code=500, detail="JWT_SECRET is not configured.")

    now = utc_now()
    rt_hash = tokens.hash_refresh_token(raw_refresh)
    doc = db.refresh_tokens.find_one({"token_hash": rt_hash})
    if not doc:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    expires_at = doc["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        db.refresh_tokens.delete_one({"id": doc["id"]})
        raise HTTPException(status_code=401, detail="Refresh token expired.")

    user_id = doc["user_id"]
    user = db.users.find_one({"id": user_id})
    if not user:
        db.refresh_tokens.delete_many({"user_id": user_id})
        raise HTTPException(status_code=401, detail="User no longer exists.")

    db.refresh_tokens.delete_one({"id": doc["id"]})
    access_token, expires_in = tokens.create_access_token(user_id)
    new_refresh = _issue_refresh_token(db, user_id)
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
    }

from datetime import UTC
import logging

import httpx
from fastapi import HTTPException
from pymongo.database import Database

from app.core import tokens
from app.core.monitoring import track_service_operation

from app.services.common import new_uuid, utc_now, user_to_api_dict
from app.services.contacts import normalize_phone_number

YANDEX_INFO_URL = "https://login.yandex.ru/info"
logger = logging.getLogger("splitapp")


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
    first_name = (
        str(profile.get("first_name")).strip() if profile.get("first_name") else ""
    ) or None
    last_name = (str(profile.get("last_name")).strip() if profile.get("last_name") else "") or None
    full_name = " ".join(part for part in [first_name, last_name] if part)
    display = (profile.get("display_name") or "").strip()
    real_name = (profile.get("real_name") or "").strip()
    login = (profile.get("login") or "").strip()
    name = display or real_name or full_name or login or yandex_id
    phone_obj = profile.get("default_phone") or {}
    phone = phone_obj.get("number") if isinstance(phone_obj, dict) else None
    phone_raw = (str(phone).strip() if phone else "") or None
    try:
        phone_number = normalize_phone_number(phone_raw) if phone_raw else f"yandex:{yandex_id}"
    except ValueError:
        phone_number = phone_raw or f"yandex:{yandex_id}"
    email_raw = profile.get("default_email")
    email = (str(email_raw).strip() if email_raw else "") or None
    avatar_raw = profile.get("default_avatar_id")
    default_avatar_id = (str(avatar_raw).strip() if avatar_raw else "") or None
    sex_raw = profile.get("sex")
    sex = (str(sex_raw).strip() if sex_raw else "") or None
    birthday_raw = profile.get("birthday")
    birthday = (str(birthday_raw).strip() if birthday_raw else "") or None
    return {
        "yandex_id": yandex_id,
        "name": name,
        "phone_number": phone_number,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "sex": sex,
        "birthday": birthday,
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


@track_service_operation("auth.login_yandex")
def login_with_yandex_oauth(db: Database, oauth_token: str) -> dict:
    try:
        tokens.ensure_jwt_secret_configured()
    except RuntimeError:
        logger.error("JWT_SECRET is not configured.", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error.")

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
                    "first_name": fields["first_name"],
                    "last_name": fields["last_name"],
                    "sex": fields["sex"],
                    "birthday": fields["birthday"],
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
            "first_name": fields["first_name"],
            "last_name": fields["last_name"],
            "sex": fields["sex"],
            "birthday": fields["birthday"],
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


@track_service_operation("auth.refresh")
def rotate_refresh_token(db: Database, raw_refresh: str) -> dict:
    try:
        tokens.ensure_jwt_secret_configured()
    except RuntimeError:
        logger.error("JWT_SECRET is not configured.", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error.")

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

    used_at = doc.get("used_at")
    if used_at is not None:
        if used_at.tzinfo is None:
            used_at = used_at.replace(tzinfo=UTC)
        if now - used_at > tokens.refresh_token_reuse_grace():
            raise HTTPException(status_code=401, detail="Invalid refresh token.")

    user_id = doc["user_id"]
    user = db.users.find_one({"id": user_id})
    if not user:
        db.refresh_tokens.delete_many({"user_id": user_id})
        raise HTTPException(status_code=401, detail="User no longer exists.")

    if used_at is None:
        reuse_expires_at = min(expires_at, now + tokens.refresh_token_reuse_grace())
        db.refresh_tokens.update_one(
            {"id": doc["id"]},
            {"$set": {"used_at": now, "expires_at": reuse_expires_at}},
        )
    access_token, expires_in = tokens.create_access_token(user_id)
    new_refresh = _issue_refresh_token(db, user_id)
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
    }

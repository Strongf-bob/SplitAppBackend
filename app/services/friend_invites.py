import hashlib
import secrets
from datetime import UTC, timedelta

from fastapi import HTTPException
from pymongo.database import Database

from app.services.access import get_user_or_404
from app.services.common import new_uuid, strip_mongo_id, utc_now, user_to_api_dict

_INVITE_TTL = timedelta(minutes=15)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _active_invite_or_error(db: Database, token: str) -> dict:
    invite = db.friend_invites.find_one({"token_hash": _hash_token(token)})
    if not invite:
        raise HTTPException(status_code=404, detail="Friend invite not found.")
    if invite["status"] != "active":
        raise HTTPException(status_code=409, detail="Friend invite is no longer active.")
    expires_at = invite["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= utc_now():
        db.friend_invites.update_one({"id": invite["id"]}, {"$set": {"status": "expired"}})
        raise HTTPException(status_code=410, detail="Friend invite has expired.")
    return invite


def create_friend_invite(db: Database, actor_user_id: str) -> dict:
    creator = get_user_or_404(db, actor_user_id)
    token = secrets.token_urlsafe(32)
    now = utc_now()
    invite = {
        "id": new_uuid(),
        "creator_id": actor_user_id,
        "token_hash": _hash_token(token),
        "status": "active",
        "expires_at": now + _INVITE_TTL,
        "created_at": now,
        "updated_at": now,
    }
    db.friend_invites.insert_one(invite)
    return {
        **strip_mongo_id(invite),
        "creator": user_to_api_dict(creator),
        "token": token,
        "invite_url": f"splitapp://friend-invite/{token}",
    }


def preview_friend_invite(db: Database, token: str, actor_user_id: str) -> dict:
    invite = _active_invite_or_error(db, token)
    if invite["creator_id"] == actor_user_id:
        raise HTTPException(status_code=400, detail="Cannot accept your own friend invite.")
    creator = get_user_or_404(db, invite["creator_id"])
    return {
        "id": invite["id"],
        "creator": user_to_api_dict(creator),
        "expires_at": invite["expires_at"],
    }

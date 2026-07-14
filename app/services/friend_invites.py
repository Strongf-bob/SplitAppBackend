import hashlib
import secrets
from datetime import UTC, timedelta

from fastapi import HTTPException
from pymongo.database import Database

from app.services.access import get_user_or_404
from app.services.common import new_uuid, utc_now, user_to_api_dict

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
        "id": invite["id"],
        "status": invite["status"],
        "expires_at": invite["expires_at"],
        "created_at": invite["created_at"],
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


def _accept_friendship(db: Database, creator_id: str, recipient_id: str) -> dict:
    pair_key = ":".join(sorted([creator_id, recipient_id]))
    existing = db.friends.find_one({"pair_key": pair_key})
    if existing and existing.get("status") == "blocked":
        raise HTTPException(status_code=403, detail="Friendship is blocked.")

    now = utc_now()
    if existing:
        db.friends.update_one(
            {"id": existing["id"]},
            {
                "$set": {
                    "requester_id": creator_id,
                    "addressee_id": recipient_id,
                    "status": "accepted",
                    "accepted_at": now,
                    "updated_at": now,
                },
                "$unset": {"deleted_at": "", "blocked_by": "", "blocked_at": ""},
            },
        )
        return db.friends.find_one({"id": existing["id"]})

    friendship = {
        "id": new_uuid(),
        "pair_key": pair_key,
        "requester_id": creator_id,
        "addressee_id": recipient_id,
        "status": "accepted",
        "accepted_at": now,
        "created_at": now,
        "updated_at": now,
    }
    db.friends.insert_one(friendship)
    return friendship


def accept_friend_invite(db: Database, token: str, actor_user_id: str) -> dict:
    token_hash = _hash_token(token)
    invite = db.friend_invites.find_one({"token_hash": token_hash})
    if invite and invite.get("status") == "accepted":
        if invite.get("accepted_by") != actor_user_id:
            raise HTTPException(status_code=409, detail="Friend invite was used by another user.")
        return db.friends.find_one({"id": invite["friendship_id"]})

    invite = _active_invite_or_error(db, token)
    if invite["creator_id"] == actor_user_id:
        raise HTTPException(status_code=400, detail="Cannot accept your own friend invite.")
    get_user_or_404(db, actor_user_id)
    friendship = _accept_friendship(db, invite["creator_id"], actor_user_id)
    result = db.friend_invites.update_one(
        {"id": invite["id"], "status": "active"},
        {
            "$set": {
                "status": "accepted",
                "accepted_by": actor_user_id,
                "friendship_id": friendship["id"],
                "accepted_at": utc_now(),
            }
        },
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="Friend invite is no longer active.")
    return friendship


def revoke_friend_invite(db: Database, invite_id: str, actor_user_id: str) -> None:
    result = db.friend_invites.update_one(
        {"id": invite_id, "creator_id": actor_user_id, "status": "active"},
        {"$set": {"status": "revoked", "revoked_at": utc_now()}},
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=404, detail="Active friend invite not found.")

import hashlib
import secrets
from datetime import UTC, timedelta

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
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
        db.friend_invites.update_one(
            {
                "id": invite["id"],
                "status": "active",
                "expires_at": invite["expires_at"],
            },
            {"$set": {"status": "expired", "updated_at": utc_now()}},
        )
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


def _accept_friendship(
    db: Database, creator_id: str, recipient_id: str, friendship_id: str
) -> dict:
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
        "id": friendship_id,
        "pair_key": pair_key,
        "requester_id": creator_id,
        "addressee_id": recipient_id,
        "status": "accepted",
        "accepted_at": now,
        "created_at": now,
        "updated_at": now,
    }
    try:
        db.friends.insert_one(friendship)
        return friendship
    except DuplicateKeyError:
        existing = db.friends.find_one({"id": friendship_id})
        if existing:
            return existing
        raise


def _ensure_pair_is_not_blocked(db: Database, creator_id: str, recipient_id: str) -> None:
    pair_key = ":".join(sorted([creator_id, recipient_id]))
    existing = db.friends.find_one({"pair_key": pair_key})
    if existing and existing.get("status") == "blocked":
        raise HTTPException(status_code=403, detail="Friendship is blocked.")


def _complete_claimed_invite(db: Database, invite: dict, actor_user_id: str) -> dict:
    friendship = _accept_friendship(
        db,
        invite["creator_id"],
        actor_user_id,
        invite["friendship_id"],
    )
    db.friend_invites.update_one(
        {
            "id": invite["id"],
            "status": "accepting",
            "accepted_by": actor_user_id,
            "friendship_id": invite["friendship_id"],
        },
        {
            "$set": {
                "status": "accepted",
                "accepted_at": utc_now(),
                "updated_at": utc_now(),
            }
        },
    )
    return friendship


def accept_friend_invite(db: Database, token: str, actor_user_id: str) -> dict:
    token_hash = _hash_token(token)
    invite = db.friend_invites.find_one({"token_hash": token_hash})
    if invite and invite.get("status") == "accepted":
        if invite.get("accepted_by") != actor_user_id:
            raise HTTPException(status_code=409, detail="Friend invite was used by another user.")
        return db.friends.find_one({"id": invite["friendship_id"]})
    if invite and invite.get("status") == "accepting":
        if invite.get("accepted_by") != actor_user_id:
            raise HTTPException(status_code=409, detail="Friend invite was used by another user.")
        return _complete_claimed_invite(db, invite, actor_user_id)

    invite = _active_invite_or_error(db, token)
    if invite["creator_id"] == actor_user_id:
        raise HTTPException(status_code=400, detail="Cannot accept your own friend invite.")
    get_user_or_404(db, actor_user_id)
    _ensure_pair_is_not_blocked(db, invite["creator_id"], actor_user_id)

    friendship_id = new_uuid()
    result = db.friend_invites.update_one(
        {
            "id": invite["id"],
            "status": "active",
            "expires_at": invite["expires_at"],
        },
        {
            "$set": {
                "status": "accepting",
                "accepted_by": actor_user_id,
                "friendship_id": friendship_id,
                "claim_started_at": utc_now(),
                "updated_at": utc_now(),
            }
        },
    )
    if result.modified_count != 1:
        claimed = db.friend_invites.find_one({"token_hash": token_hash})
        if (
            claimed
            and claimed.get("status") == "accepted"
            and claimed.get("accepted_by") == actor_user_id
        ):
            return db.friends.find_one({"id": claimed["friendship_id"]})
        raise HTTPException(status_code=409, detail="Friend invite is no longer active.")

    claimed = db.friend_invites.find_one({"id": invite["id"]})
    return _complete_claimed_invite(db, claimed, actor_user_id)


def revoke_friend_invite(db: Database, invite_id: str, actor_user_id: str) -> None:
    result = db.friend_invites.update_one(
        {"id": invite_id, "creator_id": actor_user_id, "status": "active"},
        {"$set": {"status": "revoked", "revoked_at": utc_now()}},
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=404, detail="Active friend invite not found.")

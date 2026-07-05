from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.services.access import get_user_or_404
from app.services.common import active_filter, new_uuid, strip_mongo_id, user_to_api_dict, utc_now


def _pair_key(user_a: str, user_b: str) -> str:
    return ":".join(sorted([user_a, user_b]))


def _friendship_to_api(db: Database, friendship: dict, actor_user_id: str | None = None) -> dict:
    cleaned = strip_mongo_id(friendship)
    if actor_user_id:
        peer_id = (
            friendship["addressee_id"]
            if friendship["requester_id"] == actor_user_id
            else friendship["requester_id"]
        )
        peer = db.users.find_one({"id": peer_id})
        cleaned["peer"] = user_to_api_dict(peer) if peer else None
    return cleaned


def _get_friendship_or_404(db: Database, friendship_id: str) -> dict:
    friendship = db.friends.find_one(active_filter({"id": friendship_id}))
    if not friendship:
        raise HTTPException(status_code=404, detail="Friendship not found.")
    return friendship


def _assert_party(friendship: dict, actor_user_id: str) -> None:
    if actor_user_id not in {friendship["requester_id"], friendship["addressee_id"]}:
        raise HTTPException(status_code=403, detail="Not a party to this friendship.")


@track_service_operation("friends.create")
def create_friend_request(
    db: Database, payload: schemas.FriendRequestCreate, actor_user_id: str
) -> dict:
    target_user_id = str(payload.user_id)
    get_user_or_404(db, actor_user_id)
    get_user_or_404(db, target_user_id)
    if target_user_id == actor_user_id:
        raise HTTPException(status_code=400, detail="Cannot friend yourself.")

    pair_key = _pair_key(actor_user_id, target_user_id)
    existing = db.friends.find_one(active_filter({"pair_key": pair_key}))
    if existing and existing["status"] in {"requested", "accepted", "blocked"}:
        return _friendship_to_api(db, existing, actor_user_id)

    now = utc_now()
    friendship = {
        "id": new_uuid(),
        "pair_key": pair_key,
        "requester_id": actor_user_id,
        "addressee_id": target_user_id,
        "status": "requested",
        "created_at": now,
        "updated_at": now,
    }
    db.friends.insert_one(friendship)
    record_domain_event("friends", "requested")
    return _friendship_to_api(db, friendship, actor_user_id)


@track_service_operation("friends.list")
def list_friendships(
    db: Database,
    actor_user_id: str,
    *,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> dict:
    query = active_filter(
        {"$or": [{"requester_id": actor_user_id}, {"addressee_id": actor_user_id}]}
    )
    if status_filter:
        query["status"] = status_filter
    total = db.friends.count_documents(query)
    cursor = db.friends.find(query).sort("updated_at", -1).skip(offset).limit(limit)
    return {
        "items": [_friendship_to_api(db, friendship, actor_user_id) for friendship in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("friends.accept")
def accept_friend_request(db: Database, friendship_id: str, actor_user_id: str) -> dict:
    friendship = _get_friendship_or_404(db, friendship_id)
    if actor_user_id != friendship["addressee_id"]:
        raise HTTPException(status_code=403, detail="Only addressee can accept.")
    if friendship["status"] != "requested":
        raise HTTPException(status_code=409, detail="Friend request is not pending.")

    now = utc_now()
    db.friends.update_one(
        {"id": friendship_id},
        {"$set": {"status": "accepted", "accepted_at": now, "updated_at": now}},
    )
    record_domain_event("friends", "accepted")
    return _friendship_to_api(db, _get_friendship_or_404(db, friendship_id), actor_user_id)


@track_service_operation("friends.reject")
def reject_friend_request(db: Database, friendship_id: str, actor_user_id: str) -> dict:
    friendship = _get_friendship_or_404(db, friendship_id)
    if actor_user_id != friendship["addressee_id"]:
        raise HTTPException(status_code=403, detail="Only addressee can reject.")
    if friendship["status"] != "requested":
        raise HTTPException(status_code=409, detail="Friend request is not pending.")

    now = utc_now()
    db.friends.update_one(
        {"id": friendship_id},
        {"$set": {"status": "rejected", "rejected_at": now, "updated_at": now}},
    )
    record_domain_event("friends", "rejected")
    return _friendship_to_api(db, _get_friendship_or_404(db, friendship_id), actor_user_id)


@track_service_operation("friends.remove")
def remove_friendship(db: Database, friendship_id: str, actor_user_id: str) -> None:
    friendship = _get_friendship_or_404(db, friendship_id)
    _assert_party(friendship, actor_user_id)
    now = utc_now()
    db.friends.update_one(
        {"id": friendship_id},
        {"$set": {"status": "removed", "removed_at": now, "updated_at": now}},
    )
    record_domain_event("friends", "removed")


@track_service_operation("friends.block")
def block_friendship(db: Database, friendship_id: str, actor_user_id: str) -> dict:
    friendship = _get_friendship_or_404(db, friendship_id)
    _assert_party(friendship, actor_user_id)
    now = utc_now()
    db.friends.update_one(
        {"id": friendship_id},
        {
            "$set": {
                "status": "blocked",
                "blocked_by": actor_user_id,
                "blocked_at": now,
                "updated_at": now,
            }
        },
    )
    record_domain_event("friends", "blocked")
    return _friendship_to_api(db, _get_friendship_or_404(db, friendship_id), actor_user_id)

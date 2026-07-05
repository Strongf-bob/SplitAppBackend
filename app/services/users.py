from fastapi import HTTPException
from pymongo.database import Database
import re

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.core.rate_limit import check_rate_limit
from app.services.access import get_user_or_404
from app.services.balances import get_event_balances
from app.services.common import record_audit_event, user_to_api_dict
from app.services.common import utc_now


_HANDLE_RE = re.compile(r"^[a-z0-9_]{3,32}$")
_PHONE_VISIBILITIES = {"nobody", "event_members", "friends"}


def _search_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _normalize_handle(value: str) -> str:
    handle = value.strip().casefold().removeprefix("@")
    if not _HANDLE_RE.match(handle):
        raise HTTPException(
            status_code=400,
            detail="public_handle must be 3-32 chars: lowercase letters, digits, underscore.",
        )
    return handle


def _shared_active_event_user_ids(db: Database, actor_user_id: str) -> set[str]:
    event_ids = [
        membership["event_id"]
        for membership in db.event_memberships.find(
            {
                "user_id": actor_user_id,
                "status": "active",
                "deleted_at": {"$exists": False},
            }
        )
    ]
    return {
        membership["user_id"]
        for membership in db.event_memberships.find(
            {
                "event_id": {"$in": event_ids},
                "status": "active",
                "deleted_at": {"$exists": False},
            }
        )
    }


def _accepted_friend_user_ids(db: Database, actor_user_id: str) -> set[str]:
    friend_ids: set[str] = set()
    for friendship in db.friends.find(
        {
            "status": "accepted",
            "deleted_at": {"$exists": False},
            "$or": [{"requester_id": actor_user_id}, {"addressee_id": actor_user_id}],
        }
    ):
        friend_ids.add(
            friendship["addressee_id"]
            if friendship["requester_id"] == actor_user_id
            else friendship["requester_id"]
        )
    return friend_ids


def _user_to_visible_api_dict(db: Database, user: dict, actor_user_id: str) -> dict:
    data = user_to_api_dict(user)
    if user["id"] == actor_user_id:
        return data

    visibility = user.get("payment_phone_visibility", "nobody")
    allowed = False
    if visibility == "event_members":
        allowed = user["id"] in _shared_active_event_user_ids(db, actor_user_id)
    elif visibility == "friends":
        allowed = user["id"] in _accepted_friend_user_ids(db, actor_user_id)

    if not allowed:
        data["payment_phone"] = None
    return data


@track_service_operation("users.list")
def list_users(db: Database, actor_user_id: str, *, limit: int, offset: int) -> dict:
    visible_user_ids = {actor_user_id}
    event_ids = [
        membership["event_id"]
        for membership in db.event_memberships.find(
            {
                "user_id": actor_user_id,
                "status": "active",
                "deleted_at": {"$exists": False},
            }
        )
    ]
    for membership in db.event_memberships.find(
        {
            "event_id": {"$in": event_ids},
            "status": "active",
            "deleted_at": {"$exists": False},
        }
    ):
        visible_user_ids.add(membership["user_id"])

    query = {"id": {"$in": sorted(visible_user_ids)}}
    total = db.users.count_documents(query)
    cursor = db.users.find(query).sort("name", 1).skip(offset).limit(limit)
    return {
        "items": [_user_to_visible_api_dict(db, user, actor_user_id) for user in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("users.get_current")
def get_current_user(db: Database, actor_user_id: str) -> dict:
    return _user_to_visible_api_dict(db, get_user_or_404(db, actor_user_id), actor_user_id)


@track_service_operation("users.financial_stats")
def get_current_user_financial_stats(db: Database, actor_user_id: str) -> dict:
    get_user_or_404(db, actor_user_id)
    open_events_count = 0
    closed_events_count = 0
    outstanding_owed_kopecks = 0
    outstanding_receivable_kopecks = 0

    memberships = db.event_memberships.find(
        {
            "user_id": actor_user_id,
            "status": "active",
            "deleted_at": {"$exists": False},
        }
    )
    for membership in memberships:
        event = db.events.find_one(
            {
                "id": membership["event_id"],
                "deleted_at": {"$exists": False},
            }
        )
        if not event:
            continue
        if event.get("is_closed"):
            closed_events_count += 1
        else:
            open_events_count += 1

        for row in get_event_balances(db, event["id"], actor_user_id):
            if row["debitor_id"] == actor_user_id:
                outstanding_owed_kopecks += row["amount_kopecks"]
            if row["creditor_id"] == actor_user_id:
                outstanding_receivable_kopecks += row["amount_kopecks"]

    return {
        "open_events_count": open_events_count,
        "closed_events_count": closed_events_count,
        "outstanding_owed_kopecks": outstanding_owed_kopecks,
        "outstanding_receivable_kopecks": outstanding_receivable_kopecks,
    }


@track_service_operation("users.update_current")
def update_current_user(db: Database, actor_user_id: str, payload: schemas.UserUpdate) -> dict:
    current_user = get_user_or_404(db, actor_user_id)
    update_fields: dict[str, object | None] = {}

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty.")
        update_fields["name"] = name

    if payload.email is not None:
        email = payload.email.strip()
        update_fields["email"] = email or None

    if payload.avatar_url is not None:
        avatar_url = payload.avatar_url.strip()
        update_fields["avatar_url"] = avatar_url or None

    if payload.public_handle is not None:
        raw_handle = payload.public_handle.strip()
        if raw_handle:
            public_handle = _normalize_handle(raw_handle)
            existing = db.users.find_one(
                {"public_handle": public_handle, "id": {"$ne": actor_user_id}}
            )
            if existing:
                raise HTTPException(status_code=409, detail="public_handle is already taken.")
            update_fields["public_handle"] = public_handle
        else:
            update_fields["public_handle"] = None

    if payload.discovery_enabled is not None:
        update_fields["discovery_enabled"] = payload.discovery_enabled

    if payload.payment_phone is not None:
        payment_phone = payload.payment_phone.strip()
        update_fields["payment_phone"] = payment_phone or None
        update_fields["phone_verified"] = False

    if payload.payment_phone_visibility is not None:
        visibility = payload.payment_phone_visibility.strip()
        if visibility not in _PHONE_VISIBILITIES:
            raise HTTPException(status_code=400, detail="Invalid payment_phone_visibility.")
        update_fields["payment_phone_visibility"] = visibility

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
    if "name" in update_fields or "discovery_enabled" in update_fields:
        update_fields["search_name"] = _search_name(
            str(update_fields.get("name") or current_user["name"])
        )
    db.users.update_one({"id": actor_user_id}, {"$set": update_fields})
    record_domain_event("users", "profile_updated")
    record_audit_event(
        db,
        action="user.profile_updated",
        resource_type="user",
        resource_id=actor_user_id,
        actor_user_id=actor_user_id,
    )
    return _user_to_visible_api_dict(db, get_user_or_404(db, actor_user_id), actor_user_id)


@track_service_operation("users.search")
def search_users(db: Database, actor_user_id: str, query: str, *, limit: int, offset: int) -> dict:
    get_user_or_404(db, actor_user_id)
    check_rate_limit("users.search", actor_user_id)
    term = _search_name(query)
    if len(term) < 2:
        raise HTTPException(status_code=400, detail="query must contain at least 2 characters.")

    mongo_query = {
        "id": {"$ne": actor_user_id},
        "discovery_enabled": True,
        "$or": [
            {"public_handle": {"$regex": f"^{re.escape(term)}", "$options": "i"}},
            {"search_name": {"$regex": re.escape(term), "$options": "i"}},
            {"name": {"$regex": re.escape(term), "$options": "i"}},
        ],
    }
    total = db.users.count_documents(mongo_query)
    cursor = db.users.find(mongo_query).sort("name", 1).skip(offset).limit(limit)
    return {
        "items": [_user_to_visible_api_dict(db, user, actor_user_id) for user in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }

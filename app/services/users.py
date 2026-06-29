from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.services.access import get_user_or_404
from app.services.common import record_audit_event, user_to_api_dict
from app.services.common import utc_now


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
        "items": [user_to_api_dict(user) for user in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("users.update_current")
def update_current_user(db: Database, actor_user_id: str, payload: schemas.UserUpdate) -> dict:
    get_user_or_404(db, actor_user_id)
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

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
    db.users.update_one({"id": actor_user_id}, {"$set": update_fields})
    record_domain_event("users", "profile_updated")
    record_audit_event(
        db,
        action="user.profile_updated",
        resource_type="user",
        resource_id=actor_user_id,
        actor_user_id=actor_user_id,
    )
    return user_to_api_dict(get_user_or_404(db, actor_user_id))

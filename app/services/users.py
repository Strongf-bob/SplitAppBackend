from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import track_service_operation
from app.services.access import get_user_or_404
from app.services.common import record_audit_event, user_to_api_dict
from app.services.common import utc_now


@track_service_operation("users.list")
def list_users(db: Database, actor_user_id: str, *, limit: int, offset: int) -> dict:
    visible_user_ids = {actor_user_id}
    for event in db.events.find(
        {
            "deleted_at": {"$exists": False},
            "$or": [{"users": actor_user_id}, {"creator_id": actor_user_id}],
        }
    ):
        visible_user_ids.update(event.get("users", []))
        visible_user_ids.add(event["creator_id"])

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
    record_audit_event(
        db,
        action="user.profile_updated",
        resource_type="user",
        resource_id=actor_user_id,
        actor_user_id=actor_user_id,
    )
    return user_to_api_dict(get_user_or_404(db, actor_user_id))

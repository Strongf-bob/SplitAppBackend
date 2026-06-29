from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.services.access import get_user_or_404
from app.services.common import user_to_api_dict
from app.services.common import utc_now


def list_users(db: Database) -> list[dict]:
    return [user_to_api_dict(user) for user in db.users.find({}).sort("name", 1)]


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
    return user_to_api_dict(get_user_or_404(db, actor_user_id))

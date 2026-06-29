from datetime import UTC, datetime
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


def strip_mongo_id(document: dict) -> dict:
    cleaned = dict(document)
    cleaned.pop("_id", None)
    return cleaned


def active_filter(extra: dict | None = None) -> dict:
    query = {"deleted_at": {"$exists": False}}
    if extra:
        query.update(extra)
    return query


def record_audit_event(
    db,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_user_id: str,
    session=None,
) -> None:
    db.audit_events.insert_one(
        {
            "id": new_uuid(),
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "actor_user_id": actor_user_id,
            "created_at": utc_now(),
        },
        session=session,
    )


def yandex_avatar_url(default_avatar_id: str | None) -> str | None:
    if not default_avatar_id:
        return None
    return f"https://avatars.yandex.net/get-yapic/{default_avatar_id}/islands-200"


def user_to_api_dict(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "phone_number": user["phone_number"],
        "email": user.get("email"),
        "avatar_url": user.get("avatar_url") or yandex_avatar_url(user.get("default_avatar_id")),
    }

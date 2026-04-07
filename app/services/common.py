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
        "avatar_url": yandex_avatar_url(user.get("default_avatar_id")),
    }

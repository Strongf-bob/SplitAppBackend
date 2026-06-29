from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from app.core.monitoring import monitor_db_operation


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


def decimal_from_value(value) -> Decimal:
    return Decimal(str(value))


def money_kopecks_from_value(value) -> int:
    if isinstance(value, int):
        return value
    amount = decimal_from_value(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_to_storage(value: int) -> int:
    return int(value)


def decimal_to_storage(value: Decimal) -> str:
    return str(decimal_from_value(value))


def money_round(value: Decimal) -> Decimal:
    return decimal_from_value(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def stored_money_to_kopecks(document: dict, kopecks_key: str, legacy_key: str) -> int:
    if kopecks_key in document:
        return int(document[kopecks_key])
    return money_kopecks_from_value(document[legacy_key])


def record_audit_event(
    db,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_user_id: str,
    session=None,
) -> None:
    with monitor_db_operation("audit_events.insert"):
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

from pymongo.database import Database

from app.services.access import assert_event_access
from app.services.common import strip_mongo_id


def _audit_event_to_api(audit_event: dict) -> dict:
    return strip_mongo_id(audit_event)


def _event_activity_resource_ids(db: Database, event_id: str) -> set[str]:
    resource_ids = {event_id}
    for collection_name in (
        "receipts",
        "receipt_share_reviews",
        "payments",
        "payment_requests",
        "disputes",
        "event_invites",
        "nearby_invite_codes",
        "invite_decisions",
    ):
        collection = getattr(db, collection_name)
        for item in collection.find({"event_id": event_id}):
            resource_ids.add(item["id"])
    return resource_ids


def list_event_activity(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    resource_ids = _event_activity_resource_ids(db, event_id)
    query = {"resource_id": {"$in": sorted(resource_ids)}}
    total = db.audit_events.count_documents(query)
    cursor = db.audit_events.find(query).sort("created_at", -1).skip(offset).limit(limit)
    return {
        "items": [_audit_event_to_api(item) for item in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }

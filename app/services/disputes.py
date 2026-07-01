from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.services.access import assert_event_access, get_event_or_404
from app.services.common import active_filter, new_uuid, record_audit_event, strip_mongo_id, utc_now

_RESOURCE_TYPES = {"receipt", "payment", "payment_request"}


def _dispute_to_api(dispute: dict) -> dict:
    return strip_mongo_id(dispute)


def _get_dispute_or_404(db: Database, dispute_id: str) -> dict:
    dispute = db.disputes.find_one(active_filter({"id": dispute_id}))
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found.")
    return dispute


def _resource_event_id(db: Database, resource_type: str, resource_id: str) -> str:
    if resource_type == "receipt":
        resource = db.receipts.find_one(active_filter({"id": resource_id}))
    elif resource_type == "payment":
        resource = db.payments.find_one(active_filter({"id": resource_id}))
    elif resource_type == "payment_request":
        resource = db.payment_requests.find_one(active_filter({"id": resource_id}))
    else:
        raise HTTPException(status_code=400, detail="Invalid resource_type.")
    if not resource:
        raise HTTPException(status_code=404, detail="Dispute resource not found.")
    return resource["event_id"]


@track_service_operation("disputes.create")
def create_dispute(db: Database, payload: schemas.DisputeCreate, actor_user_id: str) -> dict:
    if payload.resource_type not in _RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid resource_type.")
    resource_id = str(payload.resource_id)
    event_id = _resource_event_id(db, payload.resource_type, resource_id)
    assert_event_access(db, event_id, actor_user_id)

    now = utc_now()
    dispute = {
        "id": new_uuid(),
        "event_id": event_id,
        "resource_type": payload.resource_type,
        "resource_id": resource_id,
        "reason": payload.reason.strip(),
        "status": "open",
        "created_by": actor_user_id,
        "created_at": now,
        "updated_at": now,
        "resolution_note": "",
    }
    if not dispute["reason"]:
        raise HTTPException(status_code=400, detail="reason must be set.")
    db.disputes.insert_one(dispute)
    record_domain_event("disputes", "created")
    record_audit_event(
        db,
        action="dispute.created",
        resource_type="dispute",
        resource_id=dispute["id"],
        actor_user_id=actor_user_id,
    )
    return _dispute_to_api(dispute)


@track_service_operation("disputes.list")
def list_event_disputes(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    query = active_filter({"event_id": event_id})
    total = db.disputes.count_documents(query)
    cursor = db.disputes.find(query).sort("created_at", -1).skip(offset).limit(limit)
    return {
        "items": [_dispute_to_api(dispute) for dispute in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("disputes.resolve")
def resolve_dispute(
    db: Database, dispute_id: str, payload: schemas.DisputeResolve, actor_user_id: str
) -> dict:
    dispute = _get_dispute_or_404(db, dispute_id)
    event = get_event_or_404(db, dispute["event_id"])
    assert_event_access(db, event["id"], actor_user_id)
    if actor_user_id != event["creator_id"]:
        raise HTTPException(status_code=403, detail="Only the event creator can resolve disputes.")
    if dispute["status"] != "open":
        raise HTTPException(status_code=409, detail="Dispute is already resolved.")

    now = utc_now()
    db.disputes.update_one(
        {"id": dispute_id},
        {
            "$set": {
                "status": "resolved",
                "resolved_by": actor_user_id,
                "resolved_at": now,
                "resolution_note": payload.resolution_note,
                "updated_at": now,
            }
        },
    )
    record_domain_event("disputes", "resolved")
    record_audit_event(
        db,
        action="dispute.resolved",
        resource_type="dispute",
        resource_id=dispute_id,
        actor_user_id=actor_user_id,
    )
    return _dispute_to_api(_get_dispute_or_404(db, dispute_id))

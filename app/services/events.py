from fastapi import HTTPException
from pymongo.errors import ConfigurationError, InvalidOperation, OperationFailure
from pymongo.database import Database

from app import schemas
from app.core.monitoring import (
    observe_event_participants,
    record_domain_event,
    track_service_operation,
)

from app.services.access import (
    assert_event_access,
    assert_event_creator,
    assert_event_open,
    get_event_or_404,
    get_user_or_404,
)
from app.services.common import (
    active_filter,
    new_uuid,
    record_audit_event,
    strip_mongo_id,
    utc_now,
    user_to_api_dict,
)


@track_service_operation("events.create")
def create_event(db: Database, payload: schemas.EventCreate, actor_user_id: str) -> dict:
    creator_id = actor_user_id
    get_user_or_404(db, creator_id)

    now = utc_now()
    event = {
        "id": new_uuid(),
        "creator_id": creator_id,
        "name": payload.name.strip(),
        "is_closed": False,
        "users": [creator_id],
        "created_at": now,
        "updated_at": now,
    }
    if not event["name"]:
        raise HTTPException(status_code=400, detail="name must be set.")

    db.events.insert_one(event)
    record_domain_event("events", "created")
    observe_event_participants(len(event["users"]))
    return event


@track_service_operation("events.list")
def list_events(db: Database, user_id: str, *, limit: int, offset: int) -> dict:
    query = active_filter({"$or": [{"users": user_id}, {"creator_id": user_id}]})
    total = db.events.count_documents(query)
    cursor = db.events.find(query).sort("created_at", -1).skip(offset).limit(limit)
    events = [strip_mongo_id(event) for event in cursor]
    return {"items": events, "limit": limit, "offset": offset, "total": total}


@track_service_operation("events.get")
def get_event(db: Database, event_id: str, actor_user_id: str) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    return strip_mongo_id(event)


@track_service_operation("events.delete")
def delete_event(db: Database, event_id: str, actor_user_id: str) -> None:
    event = get_event_or_404(db, event_id)
    assert_event_creator(event, actor_user_id)
    now = utc_now()

    def delete_with_session(session) -> None:
        record_audit_event(
            db,
            action="event.deleted",
            resource_type="event",
            resource_id=event_id,
            actor_user_id=actor_user_id,
            session=session,
        )
        delete_fields = {"deleted_at": now, "deleted_by": actor_user_id, "updated_at": now}
        db.receipts.update_many(
            active_filter({"event_id": event_id}),
            {"$set": delete_fields},
            session=session,
        )
        db.payments.update_many(
            active_filter({"event_id": event_id}),
            {"$set": delete_fields},
            session=session,
        )
        db.events.update_one(
            active_filter({"id": event_id}),
            {"$set": delete_fields},
            session=session,
        )

    try:
        with db.client.start_session() as session:
            with session.start_transaction():
                delete_with_session(session)
    except (ConfigurationError, InvalidOperation, NotImplementedError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Transactional deletes require MongoDB transaction support.",
        ) from exc
    except OperationFailure as exc:
        message = str(exc).lower()
        if "transaction" in message or "replica set" in message:
            raise HTTPException(
                status_code=503,
                detail="Transactional deletes require MongoDB transaction support.",
            ) from exc
        raise
    record_domain_event("events", "deleted")


@track_service_operation("events.update")
def update_event(
    db: Database, event_id: str, payload: schemas.EventUpdate, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_creator(event, actor_user_id)
    update_fields: dict = {}

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty.")
        update_fields["name"] = name

    if payload.is_closed is not None:
        update_fields["is_closed"] = payload.is_closed

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
    db.events.update_one({"id": event["id"]}, {"$set": update_fields})
    record_domain_event("events", "updated")
    if "is_closed" in update_fields:
        action = "closed" if update_fields["is_closed"] else "reopened"
        record_domain_event("events", action)
    return strip_mongo_id(get_event_or_404(db, event_id))


@track_service_operation("events.add_participants")
def add_participants(
    db: Database, event_id: str, payload: schemas.AddParticipantsRequest, actor_user_id: str
) -> list[dict]:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_creator(event, actor_user_id)
    assert_event_open(event)
    incoming_ids = [str(user_id) for user_id in payload.user_ids]
    unknown_ids = [user_id for user_id in incoming_ids if not db.users.find_one({"id": user_id})]
    if unknown_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Users not found: {', '.join(unknown_ids)}",
        )

    new_users = sorted(set(event["users"]) | set(incoming_ids))
    db.events.update_one(
        {"id": event_id},
        {"$set": {"users": new_users, "updated_at": utc_now()}},
    )
    record_domain_event("events", "participants_added")
    observe_event_participants(len(new_users))

    users = []
    for user in db.users.find({"id": {"$in": incoming_ids}}):
        users.append(user_to_api_dict(user))
    return users


@track_service_operation("events.remove_participant")
def remove_participant(db: Database, event_id: str, user_id: str, actor_user_id: str) -> None:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_creator(event, actor_user_id)
    assert_event_open(event)
    if user_id not in event["users"]:
        raise HTTPException(status_code=404, detail="Participant not found in event.")
    if user_id == event["creator_id"]:
        raise HTTPException(status_code=400, detail="Cannot remove event creator.")

    new_users = [uid for uid in event["users"] if uid != user_id]
    db.events.update_one(
        {"id": event_id},
        {"$set": {"users": new_users, "updated_at": utc_now()}},
    )
    record_domain_event("events", "participants_removed")
    observe_event_participants(len(new_users))

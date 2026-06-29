import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from pymongo.errors import ConfigurationError, InvalidOperation, OperationFailure
from pymongo.database import Database

from app import schemas
from app.core.monitoring import (
    observe_event_participants,
    record_domain_event,
    track_service_operation,
)
from app.core.rate_limit import check_rate_limit

from app.services.access import (
    active_event_memberships,
    active_event_user_ids,
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

_EVENT_POLICY_OPTIONS = {
    "split_strategy": {"equal_default", "itemized_creator", "itemized_self_select", "agent_assisted"},
    "receipt_creation_policy": {"creator_only", "participants_can_add"},
    "receipt_finalization_policy": {
        "creator_finalizes",
        "payer_finalizes",
        "all_involved_confirm",
    },
    "participants_invite_policy": {
        "creator_only",
        "participants_can_invite_with_approval",
        "participants_can_invite_directly",
    },
    "debt_display_mode": {"simplified_default", "raw_default", "show_both"},
    "settlement_deadline_policy": {
        "disabled",
        "soft_deadline",
        "strict_deadline_with_reliability_score",
    },
}

_EVENT_POLICY_DEFAULTS = {
    "split_strategy": "equal_default",
    "receipt_creation_policy": "participants_can_add",
    "receipt_finalization_policy": "payer_finalizes",
    "participants_invite_policy": "creator_only",
    "debt_display_mode": "simplified_default",
    "settlement_deadline_policy": "disabled",
}


def _validate_event_policy(field: str, value: str) -> str:
    if value not in _EVENT_POLICY_OPTIONS[field]:
        raise HTTPException(status_code=400, detail=f"Invalid {field}.")
    return value


def _assert_can_create_invite(event: dict, actor_user_id: str) -> None:
    policy = event.get("participants_invite_policy", _EVENT_POLICY_DEFAULTS["participants_invite_policy"])
    if policy == "creator_only" and actor_user_id != event["creator_id"]:
        raise HTTPException(status_code=403, detail="Only the event creator can invite.")
    if policy == "participants_can_invite_with_approval" and actor_user_id != event["creator_id"]:
        raise HTTPException(status_code=403, detail="Participant invites require creator approval.")


def _membership_to_api(membership: dict) -> dict:
    cleaned = strip_mongo_id(membership)
    cleaned.pop("deleted_at", None)
    return cleaned


def _event_to_api(db: Database, event: dict) -> dict:
    cleaned = strip_mongo_id(event)
    cleaned.pop("users", None)
    for field, default in _EVENT_POLICY_DEFAULTS.items():
        cleaned[field] = cleaned.get(field, default)
    cleaned["participants"] = [
        _membership_to_api(membership)
        for membership in active_event_memberships(db, cleaned["id"])
    ]
    return cleaned


def _invite_to_api(invite: dict) -> dict:
    cleaned = strip_mongo_id(invite)
    cleaned["invite_url"] = f"splitapp://invites/{cleaned['token']}"
    return cleaned


def _nearby_code_to_api(code: dict) -> dict:
    return strip_mongo_id(code)


def _upsert_membership(
    db: Database,
    *,
    event_id: str,
    user_id: str,
    role: str,
    now,
) -> None:
    existing = db.event_memberships.find_one({"event_id": event_id, "user_id": user_id})
    if existing:
        db.event_memberships.update_one(
            {"id": existing["id"]},
            {
                "$set": {
                    "role": role,
                    "status": "active",
                    "joined_at": existing.get("joined_at") or now,
                    "removed_at": None,
                    "updated_at": now,
                },
                "$unset": {"deleted_at": ""},
            },
        )
        return

    db.event_memberships.insert_one(
        {
            "id": new_uuid(),
            "event_id": event_id,
            "user_id": user_id,
            "role": role,
            "status": "active",
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )


def _get_active_invite_or_error(db: Database, token: str) -> dict:
    invite = db.event_invites.find_one({"token": token, "deleted_at": {"$exists": False}})
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite["status"] != "active":
        raise HTTPException(status_code=410, detail="Invite is no longer active.")
    expires_at = invite["expires_at"]
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= utc_now():
        db.event_invites.update_one(
            {"id": invite["id"]},
            {"$set": {"status": "expired", "updated_at": utc_now()}},
        )
        raise HTTPException(status_code=410, detail="Invite has expired.")
    return invite


def _get_active_nearby_code_or_error(db: Database, code: str) -> dict:
    invite_code = db.nearby_invite_codes.find_one(
        {"code": code, "deleted_at": {"$exists": False}}
    )
    if not invite_code:
        raise HTTPException(status_code=404, detail="Nearby invite code not found.")
    if invite_code["status"] != "active":
        raise HTTPException(status_code=410, detail="Nearby invite code is no longer active.")
    expires_at = invite_code["expires_at"]
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= utc_now():
        db.nearby_invite_codes.update_one(
            {"id": invite_code["id"]},
            {"$set": {"status": "expired", "updated_at": utc_now()}},
        )
        raise HTTPException(status_code=410, detail="Nearby invite code has expired.")
    return invite_code


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
        "split_strategy": _validate_event_policy("split_strategy", payload.split_strategy),
        "receipt_creation_policy": _validate_event_policy(
            "receipt_creation_policy", payload.receipt_creation_policy
        ),
        "receipt_finalization_policy": _validate_event_policy(
            "receipt_finalization_policy", payload.receipt_finalization_policy
        ),
        "participants_invite_policy": _validate_event_policy(
            "participants_invite_policy", payload.participants_invite_policy
        ),
        "debt_display_mode": _validate_event_policy("debt_display_mode", payload.debt_display_mode),
        "settlement_deadline_policy": _validate_event_policy(
            "settlement_deadline_policy", payload.settlement_deadline_policy
        ),
        "created_at": now,
        "updated_at": now,
    }
    if not event["name"]:
        raise HTTPException(status_code=400, detail="name must be set.")

    db.events.insert_one(event)
    _upsert_membership(db, event_id=event["id"], user_id=creator_id, role="creator", now=now)
    record_domain_event("events", "created")
    observe_event_participants(1)
    return _event_to_api(db, event)


@track_service_operation("events.list")
def list_events(db: Database, user_id: str, *, limit: int, offset: int) -> dict:
    membership_query = {"user_id": user_id, "status": "active", "deleted_at": {"$exists": False}}
    event_ids = [membership["event_id"] for membership in db.event_memberships.find(membership_query)]
    query = active_filter({"id": {"$in": event_ids}})
    total = db.events.count_documents(query)
    cursor = db.events.find(query).sort("created_at", -1).skip(offset).limit(limit)
    items = [_event_to_api(db, event) for event in cursor]
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@track_service_operation("events.get")
def get_event(db: Database, event_id: str, actor_user_id: str) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    return _event_to_api(db, event)


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
        db.event_memberships.update_many(
            {"event_id": event_id, "status": "active"},
            {"$set": {"status": "removed", "removed_at": now, **delete_fields}},
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

    for field in _EVENT_POLICY_DEFAULTS:
        value = getattr(payload, field)
        if value is not None:
            update_fields[field] = _validate_event_policy(field, value)

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
    db.events.update_one({"id": event["id"]}, {"$set": update_fields})
    record_domain_event("events", "updated")
    if "is_closed" in update_fields:
        action = "closed" if update_fields["is_closed"] else "reopened"
        record_domain_event("events", action)
    return _event_to_api(db, get_event_or_404(db, event_id))


@track_service_operation("events.add_participants")
def add_participants(
    db: Database, event_id: str, payload: schemas.AddParticipantsRequest, actor_user_id: str
) -> list[dict]:
    event = assert_event_access(db, event_id, actor_user_id)
    _assert_can_create_invite(event, actor_user_id)
    assert_event_open(event)
    incoming_ids = [str(user_id) for user_id in payload.user_ids]
    unknown_ids = [user_id for user_id in incoming_ids if not db.users.find_one({"id": user_id})]
    if unknown_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Users not found: {', '.join(unknown_ids)}",
        )

    now = utc_now()
    for user_id in incoming_ids:
        _upsert_membership(db, event_id=event_id, user_id=user_id, role="member", now=now)
    db.events.update_one({"id": event_id}, {"$set": {"updated_at": now}})
    record_domain_event("events", "participants_added")
    observe_event_participants(len(active_event_user_ids(db, event_id)))

    users = []
    for user in db.users.find({"id": {"$in": incoming_ids}}):
        users.append(user_to_api_dict(user))
    return users


@track_service_operation("events.remove_participant")
def remove_participant(db: Database, event_id: str, user_id: str, actor_user_id: str) -> None:
    event = assert_event_access(db, event_id, actor_user_id)
    _assert_can_create_invite(event, actor_user_id)
    assert_event_open(event)
    if user_id not in active_event_user_ids(db, event_id):
        raise HTTPException(status_code=404, detail="Participant not found in event.")
    if user_id == event["creator_id"]:
        raise HTTPException(status_code=400, detail="Cannot remove event creator.")

    now = utc_now()
    db.events.update_one(
        {"id": event_id},
        {"$set": {"updated_at": now}},
    )
    db.event_memberships.update_one(
        {"event_id": event_id, "user_id": user_id, "status": "active"},
        {"$set": {"status": "removed", "removed_at": now, "updated_at": now}},
    )
    record_domain_event("events", "participants_removed")
    observe_event_participants(len(active_event_user_ids(db, event_id)))


@track_service_operation("events.invites.create")
def create_event_invite(
    db: Database,
    event_id: str,
    payload: schemas.CreateEventInviteRequest,
    actor_user_id: str,
) -> dict:
    check_rate_limit("events.invites.create", actor_user_id)
    event = assert_event_access(db, event_id, actor_user_id)
    _assert_can_create_invite(event, actor_user_id)
    assert_event_open(event)

    now = utc_now()
    invite = {
        "id": new_uuid(),
        "event_id": event_id,
        "token": secrets.token_urlsafe(24),
        "status": "active",
        "created_by": actor_user_id,
        "expires_at": now + timedelta(seconds=payload.expires_in_seconds),
        "created_at": now,
        "updated_at": now,
        "accepted_by": None,
        "accepted_at": None,
        "revoked_at": None,
    }
    db.event_invites.insert_one(invite)
    record_domain_event("events", "invite_created")
    return _invite_to_api(invite)


@track_service_operation("events.invites.preview")
def preview_event_invite(db: Database, token: str, actor_user_id: str) -> dict:
    check_rate_limit("events.invites.preview", actor_user_id)
    get_user_or_404(db, actor_user_id)
    invite = _get_active_invite_or_error(db, token)
    event = get_event_or_404(db, invite["event_id"])
    return {
        "event_id": event["id"],
        "event_name": event["name"],
        "creator_id": event["creator_id"],
        "expires_at": invite["expires_at"],
        "participant_count": len(active_event_user_ids(db, event["id"])),
    }


@track_service_operation("events.invites.accept")
def accept_event_invite(db: Database, token: str, actor_user_id: str) -> dict:
    check_rate_limit("events.invites.accept", actor_user_id)
    get_user_or_404(db, actor_user_id)
    invite = _get_active_invite_or_error(db, token)
    event = get_event_or_404(db, invite["event_id"])
    assert_event_open(event)

    now = utc_now()
    _upsert_membership(
        db,
        event_id=event["id"],
        user_id=actor_user_id,
        role="member" if actor_user_id != event["creator_id"] else "creator",
        now=now,
    )
    db.event_invites.update_one(
        {"id": invite["id"]},
        {
            "$set": {
                "accepted_by": actor_user_id,
                "accepted_at": now,
                "updated_at": now,
            }
        },
    )
    db.events.update_one({"id": event["id"]}, {"$set": {"updated_at": now}})
    record_domain_event("events", "invite_accepted")
    observe_event_participants(len(active_event_user_ids(db, event["id"])))
    return _event_to_api(db, get_event_or_404(db, event["id"]))


@track_service_operation("events.invites.revoke")
def revoke_event_invite(
    db: Database, event_id: str, invite_id: str, actor_user_id: str
) -> None:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_creator(event, actor_user_id)
    invite = db.event_invites.find_one(
        {"id": invite_id, "event_id": event_id, "deleted_at": {"$exists": False}}
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite["status"] != "active":
        raise HTTPException(status_code=409, detail="Invite is not active.")
    now = utc_now()
    db.event_invites.update_one(
        {"id": invite_id},
        {"$set": {"status": "revoked", "revoked_at": now, "updated_at": now}},
    )
    record_domain_event("events", "invite_revoked")


@track_service_operation("events.nearby_codes.create")
def create_nearby_invite_code(
    db: Database,
    event_id: str,
    payload: schemas.CreateNearbyInviteCodeRequest,
    actor_user_id: str,
) -> dict:
    check_rate_limit("events.nearby_codes.create", actor_user_id)
    event = assert_event_access(db, event_id, actor_user_id)
    _assert_can_create_invite(event, actor_user_id)
    assert_event_open(event)

    now = utc_now()
    for _ in range(10):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if not db.nearby_invite_codes.find_one({"code": code, "status": "active"}):
            break
    else:
        raise HTTPException(status_code=503, detail="Could not allocate nearby invite code.")

    invite_code = {
        "id": new_uuid(),
        "event_id": event_id,
        "code": code,
        "status": "active",
        "created_by": actor_user_id,
        "expires_at": now + timedelta(seconds=payload.expires_in_seconds),
        "created_at": now,
        "updated_at": now,
    }
    db.nearby_invite_codes.insert_one(invite_code)
    record_domain_event("events", "nearby_code_created")
    return _nearby_code_to_api(invite_code)


@track_service_operation("events.nearby_codes.preview")
def preview_nearby_invite_code(db: Database, code: str, actor_user_id: str) -> dict:
    check_rate_limit("events.nearby_codes.preview", actor_user_id)
    get_user_or_404(db, actor_user_id)
    invite_code = _get_active_nearby_code_or_error(db, code)
    event = get_event_or_404(db, invite_code["event_id"])
    return {
        "event_id": event["id"],
        "event_name": event["name"],
        "creator_id": event["creator_id"],
        "expires_at": invite_code["expires_at"],
        "participant_count": len(active_event_user_ids(db, event["id"])),
    }


@track_service_operation("events.nearby_codes.accept")
def accept_nearby_invite_code(db: Database, code: str, actor_user_id: str) -> dict:
    check_rate_limit("events.nearby_codes.accept", actor_user_id)
    get_user_or_404(db, actor_user_id)
    invite_code = _get_active_nearby_code_or_error(db, code)
    event = get_event_or_404(db, invite_code["event_id"])
    assert_event_open(event)

    now = utc_now()
    _upsert_membership(
        db,
        event_id=event["id"],
        user_id=actor_user_id,
        role="member" if actor_user_id != event["creator_id"] else "creator",
        now=now,
    )
    db.nearby_invite_codes.update_one(
        {"id": invite_code["id"]},
        {"$set": {"accepted_by": actor_user_id, "accepted_at": now, "updated_at": now}},
    )
    db.events.update_one({"id": event["id"]}, {"$set": {"updated_at": now}})
    record_domain_event("events", "nearby_code_accepted")
    observe_event_participants(len(active_event_user_ids(db, event["id"])))
    return _event_to_api(db, get_event_or_404(db, event["id"]))

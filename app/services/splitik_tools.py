import re
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from pymongo.database import Database

from app import schemas
from app.services.access import active_event_memberships, assert_event_access
from app.services.common import new_uuid, strip_mongo_id, utc_now
from app.services.events import create_event
from app.services.receipts import create_receipt


def draft_to_api(draft: dict) -> dict:
    cleaned = strip_mongo_id(draft)
    cleaned.pop("owner_user_id", None)
    return cleaned


def create_event_draft(
    db: Database,
    *,
    actor_user_id: str,
    session_id: str | None,
    payload: dict,
    source: str = "text",
) -> dict:
    now = utc_now()
    draft = {
        "id": new_uuid(),
        "owner_user_id": actor_user_id,
        "session_id": session_id,
        "type": "create_event",
        "status": "pending",
        "payload": payload,
        "version": 1,
        "source": source,
        "attachment_ids": [],
        "questions": [],
        "model_metadata": {},
        "created_at": now,
        "updated_at": now,
    }
    db.splitik_drafts.insert_one(draft)
    return draft_to_api(draft)


def create_receipt_draft(
    db: Database,
    *,
    actor_user_id: str,
    session_id: str | None,
    event_id: str,
    payload: dict,
    source: str = "text",
    attachment_ids: list[str] | None = None,
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    try:
        parsed_payload = schemas.CreateReceiptRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid receipt draft payload.") from exc

    now = utc_now()
    draft = {
        "id": new_uuid(),
        "owner_user_id": actor_user_id,
        "session_id": session_id,
        "event_id": event_id,
        "type": "create_receipt",
        "status": "pending",
        "payload": parsed_payload.model_dump(mode="json"),
        "version": 1,
        "source": source,
        "attachment_ids": attachment_ids or [],
        "questions": [],
        "model_metadata": {},
        "created_at": now,
        "updated_at": now,
    }
    db.splitik_drafts.insert_one(draft)
    return draft_to_api(draft)


def update_draft(
    db: Database,
    *,
    actor_user_id: str,
    draft_id: str,
    patch: dict,
) -> dict:
    draft = db.splitik_drafts.find_one({"id": draft_id, "owner_user_id": actor_user_id})
    if not draft:
        raise HTTPException(status_code=404, detail="Splitik draft not found.")
    if draft["status"] != "pending":
        raise HTTPException(status_code=409, detail="Splitik draft is not pending.")

    payload = {**draft["payload"], **patch.get("payload", {})}
    if draft["type"] == "create_receipt":
        payload = schemas.CreateReceiptRequest.model_validate(payload).model_dump(mode="json")

    now = utc_now()
    db.splitik_drafts.update_one(
        {"id": draft_id},
        {
            "$set": {
                "payload": payload,
                "updated_at": now,
                "version": int(draft.get("version", 1)) + 1,
            }
        },
    )
    updated = db.splitik_drafts.find_one({"id": draft_id})
    return draft_to_api(updated)


def latest_pending_draft(
    db: Database,
    *,
    actor_user_id: str,
    session_id: str,
    draft_type: str | None = None,
) -> dict | None:
    query = {"owner_user_id": actor_user_id, "session_id": session_id, "status": "pending"}
    if draft_type:
        query["type"] = draft_type
    return db.splitik_drafts.find_one(query, sort=[("updated_at", -1)])


def get_draft(db: Database, *, actor_user_id: str, draft_id: str) -> dict:
    draft = db.splitik_drafts.find_one({"id": draft_id, "owner_user_id": actor_user_id})
    if not draft:
        raise HTTPException(status_code=404, detail="Splitik draft not found.")
    return draft_to_api(draft)


def commit_draft(db: Database, *, actor_user_id: str, draft_id: str) -> dict:
    draft = db.splitik_drafts.find_one({"id": draft_id, "owner_user_id": actor_user_id})
    if not draft:
        raise HTTPException(status_code=404, detail="Splitik draft not found.")
    if draft["status"] != "pending":
        raise HTTPException(status_code=409, detail="Splitik draft is not pending.")

    if draft["type"] == "create_event":
        resource = create_event(
            db, schemas.EventCreate(name=draft["payload"]["name"]), actor_user_id
        )
    elif draft["type"] == "create_receipt":
        resource = create_receipt(
            db,
            draft["event_id"],
            schemas.CreateReceiptRequest.model_validate(draft["payload"]),
            actor_user_id,
            idempotency_key=f"splitik-draft:{draft_id}",
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported Splitik draft type.")

    now = utc_now()
    db.splitik_drafts.update_one(
        {"id": draft_id},
        {
            "$set": {
                "status": "committed",
                "committed_at": now,
                "committed_resource_id": resource["id"],
                "updated_at": now,
            }
        },
    )
    committed = db.splitik_drafts.find_one({"id": draft_id})
    return {"draft": draft_to_api(committed), "resource": resource}


def amount_kopecks_from_text(message: str) -> int | None:
    match = re.search(r"(\d+(?:[,.]\d{1,2})?)\s*(?:руб|₽|р\b)?", message.casefold())
    if not match:
        return None
    value = Decimal(match.group(1).replace(",", "."))
    return int(value * 100)


def build_simple_receipt_payload(
    db: Database,
    *,
    event_id: str,
    actor_user_id: str,
    message: str,
) -> dict | None:
    amount_kopecks = amount_kopecks_from_text(message)
    if not amount_kopecks:
        return None
    memberships = active_event_memberships(db, event_id)
    member_ids = [membership["user_id"] for membership in memberships]
    if not member_ids:
        return None
    share_value = Decimal("1") / Decimal(len(member_ids))
    return schemas.CreateReceiptRequest(
        payer_id=actor_user_id,
        title="Черновик чека",
        category=None,
        total_amount_kopecks=amount_kopecks,
        items=[
            schemas.CreateReceiptItemRequest(
                name="Позиция из сообщения",
                cost_kopecks=amount_kopecks,
                split_mode="custom",
                share_items=[
                    schemas.CreateShareItemRequest(user_id=user_id, share_value=share_value)
                    for user_id in member_ids
                ],
            )
        ],
    ).model_dump(mode="json")

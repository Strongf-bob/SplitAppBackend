from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import observe_money_amount, record_domain_event, track_service_operation

from app.services.access import assert_event_access, assert_event_open, get_receipt_or_404
from app.services.common import active_filter, new_uuid, record_audit_event, strip_mongo_id, utc_now
from app.services.common import (
    decimal_from_value,
    decimal_to_storage,
    money_to_storage,
    stored_money_to_kopecks,
)
from app.services.idempotency import run_idempotent_create

_ONE = decimal_from_value("1")
_RECEIPT_MONEY_METADATA_FIELDS = (
    "discount_amount_kopecks",
    "service_fee_amount_kopecks",
    "delivery_fee_amount_kopecks",
    "tip_amount_kopecks",
    "rounding_adjustment_kopecks",
    "fiscal_total_amount_kopecks",
    "vat_amount_kopecks",
)


def _validate_receipt_users(
    event: dict, payer_id: str, items: list[schemas.CreateReceiptItemRequest]
) -> None:
    if payer_id not in event["users"]:
        raise HTTPException(status_code=400, detail="payer_id must belong to event users.")

    event_users = set(event["users"])
    for item in items:
        for share in item.share_items:
            share_user_id = str(share.user_id)
            if share_user_id not in event_users:
                raise HTTPException(
                    status_code=400,
                    detail=f"share user {share_user_id} is not an event participant.",
                )


def _validate_share_sum(items: list[schemas.CreateReceiptItemRequest]) -> None:
    for item in items:
        total = sum(share.share_value for share in item.share_items)
        if total != _ONE:
            raise HTTPException(
                status_code=400,
                detail="Each item share_items must sum to 1.",
            )


def _build_receipt_items(
    receipt_id: str,
    items: list[schemas.CreateReceiptItemRequest],
) -> tuple[list[dict], list[dict]]:
    stored_items: list[dict] = []
    stored_share_items: list[dict] = []

    for item in items:
        item_id = new_uuid()
        share_ids: list[str] = []

        for share in item.share_items:
            share_id = new_uuid()
            share_ids.append(share_id)
            stored_share_items.append(
                {
                    "id": share_id,
                    "receipt_item_id": item_id,
                    "user_id": str(share.user_id),
                    "share_value": decimal_to_storage(share.share_value),
                }
            )

        stored_items.append(
            {
                "id": item_id,
                "receipt_id": receipt_id,
                "name": item.name,
                "cost_kopecks": money_to_storage(item.cost_kopecks),
                "split_mode": item.split_mode,
                "share_items": share_ids,
            }
        )

    return stored_items, stored_share_items


def _assert_can_create_receipt(event: dict, actor_user_id: str) -> None:
    policy = event.get("receipt_creation_policy", "participants_can_add")
    if policy == "creator_only" and actor_user_id != event["creator_id"]:
        raise HTTPException(status_code=403, detail="Only the event creator can create receipts.")


def _assert_can_confirm_receipt(event: dict, receipt: dict, actor_user_id: str) -> None:
    policy = event.get("receipt_finalization_policy", "payer_finalizes")
    if policy == "creator_finalizes" and actor_user_id != event["creator_id"]:
        raise HTTPException(status_code=403, detail="Only the event creator can confirm receipts.")
    if policy == "payer_finalizes" and actor_user_id != receipt["payer_id"]:
        raise HTTPException(status_code=403, detail="Only the receipt payer can confirm this receipt.")
    if policy == "all_involved_confirm" and actor_user_id != event["creator_id"]:
        raise HTTPException(
            status_code=403,
            detail="All-involved confirmation is not implemented; creator must finalize.",
        )


def _receipt_to_api(receipt: dict, *, include_internal_shares: bool = False) -> dict:
    cleaned = strip_mongo_id(receipt)
    cleaned["status"] = cleaned.get("status", "confirmed")
    cleaned["version"] = int(cleaned.get("version", 1))
    cleaned["total_amount_kopecks"] = stored_money_to_kopecks(
        cleaned, "total_amount_kopecks", "total_amount"
    )
    cleaned.pop("total_amount", None)

    items = []
    for item in cleaned.get("items", []):
        normalized_item = dict(item)
        normalized_item["cost_kopecks"] = stored_money_to_kopecks(
            normalized_item, "cost_kopecks", "cost"
        )
        normalized_item.pop("cost", None)
        normalized_item["split_mode"] = normalized_item.get("split_mode", "custom")
        items.append(normalized_item)
    cleaned["items"] = items
    for field in _RECEIPT_MONEY_METADATA_FIELDS:
        if field in {"fiscal_total_amount_kopecks", "vat_amount_kopecks"}:
            cleaned[field] = cleaned.get(field)
        else:
            cleaned[field] = int(cleaned.get(field, 0))

    if not include_internal_shares:
        cleaned.pop("share_items", None)
    return cleaned


@track_service_operation("receipts.create")
def create_receipt(
    db: Database,
    event_id: str,
    payload: schemas.CreateReceiptRequest,
    actor_user_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"events:{event_id}:receipts",
        key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create=lambda: _create_receipt(db, event_id, payload, actor_user_id),
    )


def _create_receipt(
    db: Database, event_id: str, payload: schemas.CreateReceiptRequest, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)
    _assert_can_create_receipt(event, actor_user_id)
    payer_id = str(payload.payer_id)
    _validate_receipt_users(event, payer_id, payload.items)
    _validate_share_sum(payload.items)

    calculated_total = sum(item.cost_kopecks for item in payload.items)
    if calculated_total != payload.total_amount_kopecks:
        raise HTTPException(
            status_code=400,
            detail="total_amount_kopecks must be equal to the sum of all item costs.",
        )

    now = utc_now()
    receipt_id = new_uuid()
    stored_items, stored_share_items = _build_receipt_items(receipt_id, payload.items)

    receipt = {
        "id": receipt_id,
        "event_id": event_id,
        "payer_id": payer_id,
        "title": payload.title,
        "status": "draft",
        "version": 1,
        "total_amount_kopecks": money_to_storage(payload.total_amount_kopecks),
        "discount_amount_kopecks": money_to_storage(payload.discount_amount_kopecks),
        "service_fee_amount_kopecks": money_to_storage(payload.service_fee_amount_kopecks),
        "delivery_fee_amount_kopecks": money_to_storage(payload.delivery_fee_amount_kopecks),
        "tip_amount_kopecks": money_to_storage(payload.tip_amount_kopecks),
        "rounding_adjustment_kopecks": money_to_storage(payload.rounding_adjustment_kopecks),
        "fiscal_total_amount_kopecks": payload.fiscal_total_amount_kopecks,
        "vat_amount_kopecks": payload.vat_amount_kopecks,
        "created_at": now,
        "updated_at": now,
        "items": stored_items,
        "share_items": stored_share_items,
    }
    db.receipts.insert_one(receipt)
    record_domain_event("receipts", "created")
    observe_money_amount("receipt_total", payload.total_amount_kopecks / 100)
    return _receipt_to_api(receipt)


@track_service_operation("receipts.update")
def update_receipt(
    db: Database, receipt_id: str, payload: schemas.UpdateReceiptRequest, actor_user_id: str
) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)
    _assert_can_confirm_receipt(event, receipt, actor_user_id)
    update_fields: dict = {}
    is_confirmed = receipt.get("status", "confirmed") == "confirmed"
    current_version = int(receipt.get("version", 1))
    if payload.expected_version is not None and payload.expected_version != current_version:
        raise HTTPException(status_code=409, detail="Receipt version conflict.")

    if payload.title is not None:
        update_fields["title"] = payload.title

    if payload.total_amount_kopecks is not None and payload.items is None:
        raise HTTPException(
            status_code=400,
            detail="total_amount_kopecks can be updated only together with items.",
        )

    if payload.items is not None:
        if is_confirmed:
            raise HTTPException(
                status_code=409,
                detail="Confirmed receipt financial fields cannot be changed.",
            )
        _validate_receipt_users(event, receipt["payer_id"], payload.items)
        _validate_share_sum(payload.items)

        calculated_total = sum(item.cost_kopecks for item in payload.items)
        if payload.total_amount_kopecks is not None and calculated_total != payload.total_amount_kopecks:
            raise HTTPException(
                status_code=400,
                detail="total_amount_kopecks must be equal to the sum of all item costs.",
            )

        update_fields["total_amount_kopecks"] = (
            money_to_storage(payload.total_amount_kopecks)
            if payload.total_amount_kopecks is not None
            else money_to_storage(calculated_total)
        )
        stored_items, stored_share_items = _build_receipt_items(receipt_id, payload.items)
        update_fields["items"] = stored_items
        update_fields["share_items"] = stored_share_items

    for field in _RECEIPT_MONEY_METADATA_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            if is_confirmed:
                raise HTTPException(
                    status_code=409,
                    detail="Confirmed receipt financial metadata cannot be changed.",
                )
            update_fields[field] = money_to_storage(value)

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
    update_fields["version"] = current_version + 1
    db.receipts.update_one({"id": receipt_id}, {"$set": update_fields})
    record_domain_event("receipts", "updated")
    if "total_amount_kopecks" in update_fields:
        observe_money_amount("receipt_total", update_fields["total_amount_kopecks"] / 100)
    return _receipt_to_api(get_receipt_or_404(db, receipt_id))


@track_service_operation("receipts.list")
def list_receipts_by_event(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    query = active_filter({"event_id": event_id})
    total = db.receipts.count_documents(query)
    receipts = []
    cursor = db.receipts.find(query).sort("created_at", -1).skip(offset).limit(limit)
    for receipt in cursor:
        receipts.append(_receipt_to_api(receipt))
    return {"items": receipts, "limit": limit, "offset": offset, "total": total}


@track_service_operation("receipts.get")
def get_receipt(db: Database, receipt_id: str, actor_user_id: str) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    assert_event_access(db, receipt["event_id"], actor_user_id)
    return _receipt_to_api(receipt)


@track_service_operation("receipts.delete")
def delete_receipt(db: Database, receipt_id: str, actor_user_id: str) -> None:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)
    now = utc_now()
    db.receipts.update_one(
        active_filter({"id": receipt_id}),
        {"$set": {"deleted_at": now, "deleted_by": actor_user_id, "updated_at": now}},
    )
    record_domain_event("receipts", "deleted")
    record_audit_event(
        db,
        action="receipt.deleted",
        resource_type="receipt",
        resource_id=receipt_id,
        actor_user_id=actor_user_id,
    )


@track_service_operation("receipts.confirm")
def confirm_receipt(db: Database, receipt_id: str, actor_user_id: str) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)
    status = receipt.get("status", "confirmed")
    if status == "confirmed":
        return _receipt_to_api(receipt)
    if status not in {"draft", "ready_for_review"}:
        raise HTTPException(
            status_code=409, detail="Only draft or ready_for_review receipts can be confirmed."
        )

    now = utc_now()
    current_version = int(receipt.get("version", 1))
    db.receipts.update_one(
        active_filter({"id": receipt_id}),
        {
            "$set": {
                "status": "confirmed",
                "confirmed_at": now,
                "updated_at": now,
                "version": current_version + 1,
            }
        },
    )
    record_domain_event("receipts", "confirmed")
    record_audit_event(
        db,
        action="receipt.confirmed",
        resource_type="receipt",
        resource_id=receipt_id,
        actor_user_id=actor_user_id,
    )
    return _receipt_to_api(get_receipt_or_404(db, receipt_id))


@track_service_operation("receipts.void")
def void_receipt(db: Database, receipt_id: str, actor_user_id: str) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != event["creator_id"] and actor_user_id != receipt["payer_id"]:
        raise HTTPException(status_code=403, detail="Only creator or payer can void receipt.")
    if receipt.get("status", "confirmed") != "confirmed":
        raise HTTPException(status_code=409, detail="Only confirmed receipts can be voided.")

    now = utc_now()
    current_version = int(receipt.get("version", 1))
    db.receipts.update_one(
        active_filter({"id": receipt_id}),
        {
            "$set": {
                "status": "voided",
                "voided_at": now,
                "voided_by": actor_user_id,
                "updated_at": now,
                "version": current_version + 1,
            }
        },
    )
    record_domain_event("receipts", "voided")
    record_audit_event(
        db,
        action="receipt.voided",
        resource_type="receipt",
        resource_id=receipt_id,
        actor_user_id=actor_user_id,
    )
    return _receipt_to_api(get_receipt_or_404(db, receipt_id))


@track_service_operation("receipts.correct")
def create_receipt_correction(db: Database, receipt_id: str, actor_user_id: str) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != event["creator_id"] and actor_user_id != receipt["payer_id"]:
        raise HTTPException(status_code=403, detail="Only creator or payer can correct receipt.")
    if receipt.get("status", "confirmed") != "confirmed":
        raise HTTPException(status_code=409, detail="Only confirmed receipts can be corrected.")

    now = utc_now()
    correction_id = new_uuid()
    items = []
    share_items = []
    item_id_map: dict[str, str] = {}
    for item in receipt.get("items", []):
        new_item = dict(item)
        old_item_id = new_item["id"]
        new_item["id"] = new_uuid()
        new_item["receipt_id"] = correction_id
        item_id_map[old_item_id] = new_item["id"]
        items.append(new_item)
    share_id_map: dict[str, str] = {}
    for share in receipt.get("share_items", []):
        new_share = dict(share)
        old_share_id = new_share["id"]
        new_share["id"] = new_uuid()
        new_share["receipt_item_id"] = item_id_map.get(
            new_share["receipt_item_id"], new_share["receipt_item_id"]
        )
        share_id_map[old_share_id] = new_share["id"]
        share_items.append(new_share)
    for item in items:
        item["share_items"] = [share_id_map.get(share_id, share_id) for share_id in item["share_items"]]

    correction = {
        "id": correction_id,
        "event_id": receipt["event_id"],
        "payer_id": receipt["payer_id"],
        "title": receipt.get("title", ""),
        "status": "draft",
        "version": 1,
        "total_amount_kopecks": stored_money_to_kopecks(
            receipt, "total_amount_kopecks", "total_amount"
        ),
        **{field: receipt.get(field, 0) for field in _RECEIPT_MONEY_METADATA_FIELDS},
        "created_at": now,
        "updated_at": now,
        "items": items,
        "share_items": share_items,
        "corrected_from_receipt_id": receipt_id,
    }
    db.receipts.insert_one(correction)
    db.receipts.update_one(
        {"id": receipt_id},
        {
            "$set": {
                "status": "corrected",
                "corrected_at": now,
                "corrected_by": actor_user_id,
                "updated_at": now,
                "version": int(receipt.get("version", 1)) + 1,
            }
        },
    )
    record_domain_event("receipts", "corrected")
    record_audit_event(
        db,
        action="receipt.corrected",
        resource_type="receipt",
        resource_id=receipt_id,
        actor_user_id=actor_user_id,
    )
    return _receipt_to_api(correction)


def _allocation_session_to_api(session: dict) -> dict:
    return strip_mongo_id(session)


def _allocation_claim_to_api(claim: dict) -> dict:
    return strip_mongo_id(claim)


def _get_allocation_session_or_404(db: Database, session_id: str) -> dict:
    session = db.receipt_allocation_sessions.find_one(active_filter({"id": session_id}))
    if not session:
        raise HTTPException(status_code=404, detail="Allocation session not found.")
    return session


def _allocation_session_state(db: Database, session: dict) -> dict:
    claims = list(
        db.receipt_item_claims.find(
            active_filter({"session_id": session["id"], "status": "claimed"})
        ).sort("created_at", 1)
    )
    return {
        "session": _allocation_session_to_api(session),
        "claims": [_allocation_claim_to_api(claim) for claim in claims],
    }


def _assert_receipt_item_exists(receipt: dict, receipt_item_id: str) -> None:
    if receipt_item_id not in {item["id"] for item in receipt.get("items", [])}:
        raise HTTPException(status_code=404, detail="Receipt item not found.")


@track_service_operation("receipt_allocations.start")
def start_allocation_session(db: Database, receipt_id: str, actor_user_id: str) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    assert_event_open(event)
    if receipt.get("status", "confirmed") != "draft":
        raise HTTPException(status_code=409, detail="Only draft receipts can start allocation.")
    if actor_user_id not in {event["creator_id"], receipt["payer_id"]}:
        raise HTTPException(status_code=403, detail="Only creator or payer can start allocation.")

    existing = db.receipt_allocation_sessions.find_one(
        active_filter({"receipt_id": receipt_id, "status": {"$in": ["collecting", "ready"]}})
    )
    if existing:
        return _allocation_session_state(db, existing)

    now = utc_now()
    session = {
        "id": new_uuid(),
        "event_id": receipt["event_id"],
        "receipt_id": receipt_id,
        "status": "collecting",
        "created_by": actor_user_id,
        "created_at": now,
        "updated_at": now,
    }
    db.receipt_allocation_sessions.insert_one(session)
    db.receipts.update_one(
        {"id": receipt_id},
        {
            "$set": {
                "status": "collecting_shares",
                "allocation_session_id": session["id"],
                "updated_at": now,
                "version": int(receipt.get("version", 1)) + 1,
            }
        },
    )
    record_domain_event("receipt_allocations", "started")
    return _allocation_session_state(db, session)


@track_service_operation("receipt_allocations.get")
def get_allocation_session(db: Database, session_id: str, actor_user_id: str) -> dict:
    session = _get_allocation_session_or_404(db, session_id)
    assert_event_access(db, session["event_id"], actor_user_id)
    return _allocation_session_state(db, session)


@track_service_operation("receipt_allocations.claim")
def claim_receipt_item(
    db: Database,
    session_id: str,
    payload: schemas.ReceiptItemClaimRequest,
    actor_user_id: str,
) -> dict:
    session = _get_allocation_session_or_404(db, session_id)
    event = assert_event_access(db, session["event_id"], actor_user_id)
    assert_event_open(event)
    if session["status"] != "collecting":
        raise HTTPException(status_code=409, detail="Allocation session is not collecting claims.")
    receipt = get_receipt_or_404(db, session["receipt_id"])
    receipt_item_id = str(payload.receipt_item_id)
    _assert_receipt_item_exists(receipt, receipt_item_id)

    existing = db.receipt_item_claims.find_one(
        active_filter(
            {
                "session_id": session_id,
                "receipt_item_id": receipt_item_id,
                "user_id": actor_user_id,
                "status": "claimed",
            }
        )
    )
    if existing:
        return _allocation_claim_to_api(existing)

    now = utc_now()
    claim = {
        "id": new_uuid(),
        "session_id": session_id,
        "receipt_id": session["receipt_id"],
        "receipt_item_id": receipt_item_id,
        "user_id": actor_user_id,
        "status": "claimed",
        "created_at": now,
        "updated_at": now,
    }
    db.receipt_item_claims.insert_one(claim)
    record_domain_event("receipt_allocations", "item_claimed")
    return _allocation_claim_to_api(claim)


@track_service_operation("receipt_allocations.unclaim")
def unclaim_receipt_item(
    db: Database,
    session_id: str,
    payload: schemas.ReceiptItemClaimRequest,
    actor_user_id: str,
) -> None:
    session = _get_allocation_session_or_404(db, session_id)
    event = assert_event_access(db, session["event_id"], actor_user_id)
    assert_event_open(event)
    if session["status"] != "collecting":
        raise HTTPException(status_code=409, detail="Allocation session is not collecting claims.")
    receipt_item_id = str(payload.receipt_item_id)
    now = utc_now()
    db.receipt_item_claims.update_many(
        active_filter(
            {
                "session_id": session_id,
                "receipt_item_id": receipt_item_id,
                "user_id": actor_user_id,
                "status": "claimed",
            }
        ),
        {"$set": {"status": "removed", "deleted_at": now, "updated_at": now}},
    )
    record_domain_event("receipt_allocations", "item_unclaimed")


@track_service_operation("receipt_allocations.ready")
def mark_allocation_session_ready(db: Database, session_id: str, actor_user_id: str) -> dict:
    session = _get_allocation_session_or_404(db, session_id)
    event = assert_event_access(db, session["event_id"], actor_user_id)
    assert_event_open(event)
    receipt = get_receipt_or_404(db, session["receipt_id"])
    if actor_user_id not in {event["creator_id"], receipt["payer_id"]}:
        raise HTTPException(status_code=403, detail="Only creator or payer can mark ready.")
    if session["status"] != "collecting":
        raise HTTPException(status_code=409, detail="Allocation session is not collecting claims.")

    now = utc_now()
    db.receipt_allocation_sessions.update_one(
        {"id": session_id},
        {"$set": {"status": "ready", "ready_at": now, "updated_at": now}},
    )
    db.receipts.update_one(
        {"id": receipt["id"]},
        {"$set": {"status": "ready_for_review", "updated_at": now}},
    )
    record_domain_event("receipt_allocations", "ready")
    return _allocation_session_state(db, _get_allocation_session_or_404(db, session_id))


@track_service_operation("receipt_allocations.finalize")
def finalize_allocation_session(db: Database, session_id: str, actor_user_id: str) -> dict:
    session = _get_allocation_session_or_404(db, session_id)
    event = assert_event_access(db, session["event_id"], actor_user_id)
    assert_event_open(event)
    receipt = get_receipt_or_404(db, session["receipt_id"])
    if actor_user_id not in {event["creator_id"], receipt["payer_id"]}:
        raise HTTPException(status_code=403, detail="Only creator or payer can finalize allocation.")
    if session["status"] not in {"collecting", "ready"}:
        raise HTTPException(status_code=409, detail="Allocation session cannot be finalized.")

    claims = list(
        db.receipt_item_claims.find(
            active_filter({"session_id": session_id, "status": "claimed"})
        )
    )
    claims_by_item: dict[str, list[str]] = {}
    for claim in claims:
        claims_by_item.setdefault(claim["receipt_item_id"], []).append(claim["user_id"])

    stored_items: list[dict] = []
    stored_share_items: list[dict] = []
    for item in receipt.get("items", []):
        user_ids = sorted(set(claims_by_item.get(item["id"], [])))
        if not user_ids:
            raise HTTPException(status_code=400, detail="Every receipt item must have a claim.")
        share_value = decimal_to_storage(_ONE / decimal_from_value(len(user_ids)))
        share_ids = []
        for user_id in user_ids:
            share_id = new_uuid()
            share_ids.append(share_id)
            stored_share_items.append(
                {
                    "id": share_id,
                    "receipt_item_id": item["id"],
                    "user_id": user_id,
                    "share_value": share_value,
                }
            )
        updated_item = dict(item)
        updated_item["share_items"] = share_ids
        updated_item["split_mode"] = "selected_equal"
        stored_items.append(updated_item)

    now = utc_now()
    db.receipts.update_one(
        {"id": receipt["id"]},
        {
            "$set": {
                "items": stored_items,
                "share_items": stored_share_items,
                "status": "ready_for_review",
                "updated_at": now,
                "version": int(receipt.get("version", 1)) + 1,
            }
        },
    )
    db.receipt_allocation_sessions.update_one(
        {"id": session_id},
        {"$set": {"status": "finalized", "finalized_at": now, "updated_at": now}},
    )
    record_domain_event("receipt_allocations", "finalized")
    return _receipt_to_api(get_receipt_or_404(db, receipt["id"]))

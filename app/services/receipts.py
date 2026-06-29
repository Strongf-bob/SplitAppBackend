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

_ONE = decimal_from_value("1")


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
                "share_items": share_ids,
            }
        )

    return stored_items, stored_share_items


def _receipt_to_api(receipt: dict, *, include_internal_shares: bool = False) -> dict:
    cleaned = strip_mongo_id(receipt)
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
        items.append(normalized_item)
    cleaned["items"] = items

    if not include_internal_shares:
        cleaned.pop("share_items", None)
    return cleaned


@track_service_operation("receipts.create")
def create_receipt(
    db: Database, event_id: str, payload: schemas.CreateReceiptRequest, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)
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
        "total_amount_kopecks": money_to_storage(payload.total_amount_kopecks),
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
    update_fields: dict = {}

    if payload.title is not None:
        update_fields["title"] = payload.title

    if payload.total_amount_kopecks is not None and payload.items is None:
        raise HTTPException(
            status_code=400,
            detail="total_amount_kopecks can be updated only together with items.",
        )

    if payload.items is not None:
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

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
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

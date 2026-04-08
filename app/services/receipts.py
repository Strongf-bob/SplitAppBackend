from fastapi import HTTPException
from pymongo.database import Database

from app import schemas

from app.services.access import assert_event_access, get_receipt_or_404
from app.services.common import new_uuid, strip_mongo_id, utc_now


def _validate_receipt_users(event: dict, payer_id: str, items: list[schemas.CreateReceiptItemRequest]) -> None:
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
        if abs(total - 1.0) > 1e-6:
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
                    "share_value": share.share_value,
                }
            )

        stored_items.append(
            {
                "id": item_id,
                "receipt_id": receipt_id,
                "name": item.name,
                "cost": item.cost,
                "share_items": share_ids,
            }
        )

    return stored_items, stored_share_items


def create_receipt(
    db: Database, event_id: str, payload: schemas.CreateReceiptRequest, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    payer_id = str(payload.payer_id)
    _validate_receipt_users(event, payer_id, payload.items)
    _validate_share_sum(payload.items)

    calculated_total = sum(item.cost for item in payload.items)
    if abs(calculated_total - payload.total_amount) > 1e-6:
        raise HTTPException(
            status_code=400,
            detail="total_amount must be equal to the sum of all item costs.",
        )

    now = utc_now()
    receipt_id = new_uuid()
    stored_items, stored_share_items = _build_receipt_items(receipt_id, payload.items)

    receipt = {
        "id": receipt_id,
        "event_id": event_id,
        "payer_id": payer_id,
        "title": payload.title,
        "total_amount": payload.total_amount,
        "created_at": now,
        "updated_at": now,
        "items": stored_items,
        "share_items": stored_share_items,
    }
    db.receipts.insert_one(receipt)
    return strip_mongo_id(receipt)


def update_receipt(
    db: Database, receipt_id: str, payload: schemas.UpdateReceiptRequest, actor_user_id: str
) -> dict:
    receipt = get_receipt_or_404(db, receipt_id)
    event = assert_event_access(db, receipt["event_id"], actor_user_id)
    update_fields: dict = {}

    if payload.title is not None:
        update_fields["title"] = payload.title

    if payload.total_amount is not None and payload.items is None:
        raise HTTPException(
            status_code=400,
            detail="total_amount can be updated only together with items.",
        )

    if payload.items is not None:
        _validate_receipt_users(event, receipt["payer_id"], payload.items)
        _validate_share_sum(payload.items)

        calculated_total = sum(item.cost for item in payload.items)
        if payload.total_amount is not None and abs(calculated_total - payload.total_amount) > 1e-6:
            raise HTTPException(
                status_code=400,
                detail="total_amount must be equal to the sum of all item costs.",
            )

        update_fields["total_amount"] = (
            payload.total_amount if payload.total_amount is not None else calculated_total
        )
        stored_items, stored_share_items = _build_receipt_items(receipt_id, payload.items)
        update_fields["items"] = stored_items
        update_fields["share_items"] = stored_share_items

    if not update_fields:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")

    update_fields["updated_at"] = utc_now()
    db.receipts.update_one({"id": receipt_id}, {"$set": update_fields})
    return strip_mongo_id(get_receipt_or_404(db, receipt_id))


def list_receipts_by_event(db: Database, event_id: str, actor_user_id: str) -> list[dict]:
    assert_event_access(db, event_id, actor_user_id)
    receipts = []
    for receipt in db.receipts.find({"event_id": event_id}).sort("created_at", -1):
        cleaned = strip_mongo_id(receipt)
        cleaned.pop("share_items", None)
        receipts.append(cleaned)
    return receipts


def delete_receipt(db: Database, receipt_id: str, actor_user_id: str) -> None:
    receipt = get_receipt_or_404(db, receipt_id)
    assert_event_access(db, receipt["event_id"], actor_user_id)
    db.receipts.delete_one({"id": receipt_id})

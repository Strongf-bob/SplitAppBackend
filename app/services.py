from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from pymongo.database import Database

from app import schemas


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid_str() -> str:
    return str(uuid4())


def _strip_mongo_id(document: dict) -> dict:
    cleaned = dict(document)
    cleaned.pop("_id", None)
    return cleaned


def ensure_indexes(db: Database) -> None:
    db.users.create_index("id", unique=True)
    db.users.create_index("phone_number", unique=True)
    db.events.create_index("id", unique=True)
    db.receipts.create_index("id", unique=True)
    db.receipts.create_index([("event_id", 1), ("created_at", -1)])
    db.payments.create_index("id", unique=True)
    db.payments.create_index([("event_id", 1), ("created_at", -1)])


def _get_user_or_404(db: Database, user_id: str) -> dict:
    user = db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")
    return user


def _get_event_or_404(db: Database, event_id: str) -> dict:
    event = db.events.find_one({"id": event_id})
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")
    return event


def _get_receipt_or_404(db: Database, receipt_id: str) -> dict:
    receipt = db.receipts.find_one({"id": receipt_id})
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found.")
    return receipt


def _get_payment_or_404(db: Database, payment_id: str) -> dict:
    payment = db.payments.find_one({"id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found.")
    return payment


def create_user(db: Database, payload: schemas.UserCreate) -> dict:
    user = {
        "id": _uuid_str(),
        "name": payload.name.strip(),
        "phone_number": payload.phone_number.strip(),
    }
    if not user["name"] or not user["phone_number"]:
        raise HTTPException(status_code=400, detail="name and phone_number must be set.")

    if db.users.find_one({"phone_number": user["phone_number"]}):
        raise HTTPException(status_code=400, detail="phone_number must be unique.")

    db.users.insert_one(user)
    return user


def create_event(db: Database, payload: schemas.EventCreate) -> dict:
    creator_id = str(payload.creator_id)
    _get_user_or_404(db, creator_id)

    now = _now()
    event = {
        "id": _uuid_str(),
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
    return event


def list_events(db: Database, user_id: str | None) -> list[dict]:
    query: dict = {}
    if user_id:
        query = {"$or": [{"users": user_id}, {"creator_id": user_id}]}
    events = [_strip_mongo_id(event) for event in db.events.find(query).sort("created_at", -1)]
    return events


def get_event(db: Database, event_id: str) -> dict:
    return _strip_mongo_id(_get_event_or_404(db, event_id))


def update_event(db: Database, event_id: str, payload: schemas.EventUpdate) -> dict:
    event = _get_event_or_404(db, event_id)
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

    update_fields["updated_at"] = _now()
    db.events.update_one({"id": event["id"]}, {"$set": update_fields})
    return _strip_mongo_id(_get_event_or_404(db, event_id))


def add_participants(db: Database, event_id: str, payload: schemas.AddParticipantsRequest) -> list[dict]:
    event = _get_event_or_404(db, event_id)
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
        {"$set": {"users": new_users, "updated_at": _now()}},
    )

    users = []
    for user in db.users.find({"id": {"$in": incoming_ids}}):
        users.append(_strip_mongo_id(user))
    return users


def remove_participant(db: Database, event_id: str, user_id: str) -> None:
    event = _get_event_or_404(db, event_id)
    if user_id not in event["users"]:
        raise HTTPException(status_code=404, detail="Participant not found in event.")
    if user_id == event["creator_id"]:
        raise HTTPException(status_code=400, detail="Cannot remove event creator.")

    new_users = [uid for uid in event["users"] if uid != user_id]
    db.events.update_one(
        {"id": event_id},
        {"$set": {"users": new_users, "updated_at": _now()}},
    )


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
        item_id = _uuid_str()
        share_ids: list[str] = []

        for share in item.share_items:
            share_id = _uuid_str()
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


def create_receipt(db: Database, event_id: str, payload: schemas.CreateReceiptRequest) -> dict:
    event = _get_event_or_404(db, event_id)
    payer_id = str(payload.payer_id)
    _validate_receipt_users(event, payer_id, payload.items)
    _validate_share_sum(payload.items)

    calculated_total = sum(item.cost for item in payload.items)
    if abs(calculated_total - payload.total_amount) > 1e-6:
        raise HTTPException(
            status_code=400,
            detail="total_amount must be equal to the sum of all item costs.",
        )

    now = _now()
    receipt_id = _uuid_str()
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
    return _strip_mongo_id(receipt)


def update_receipt(db: Database, receipt_id: str, payload: schemas.UpdateReceiptRequest) -> dict:
    receipt = _get_receipt_or_404(db, receipt_id)
    event = _get_event_or_404(db, receipt["event_id"])
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

    update_fields["updated_at"] = _now()
    db.receipts.update_one({"id": receipt_id}, {"$set": update_fields})
    return _strip_mongo_id(_get_receipt_or_404(db, receipt_id))


def list_receipts_by_event(db: Database, event_id: str) -> list[dict]:
    _get_event_or_404(db, event_id)
    receipts = []
    for receipt in db.receipts.find({"event_id": event_id}).sort("created_at", -1):
        cleaned = _strip_mongo_id(receipt)
        cleaned.pop("share_items", None)
        receipts.append(cleaned)
    return receipts


def delete_receipt(db: Database, receipt_id: str) -> None:
    _get_receipt_or_404(db, receipt_id)
    db.receipts.delete_one({"id": receipt_id})


def create_payment(db: Database, event_id: str, payload: schemas.PaymentCreate) -> dict:
    event = _get_event_or_404(db, event_id)
    sender_id = str(payload.sender_id)
    receiver_id = str(payload.receiver_id)

    if sender_id == receiver_id:
        raise HTTPException(status_code=400, detail="sender_id and receiver_id must differ.")

    if sender_id not in event["users"] or receiver_id not in event["users"]:
        raise HTTPException(
            status_code=400,
            detail="sender_id and receiver_id must belong to event users.",
        )

    payment = {
        "id": _uuid_str(),
        "event_id": event_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount": payload.amount,
        "confirmed": False,
        "created_at": _now(),
    }
    db.payments.insert_one(payment)
    return payment


def list_payments_by_event(db: Database, event_id: str) -> list[dict]:
    _get_event_or_404(db, event_id)
    return [_strip_mongo_id(item) for item in db.payments.find({"event_id": event_id}).sort("created_at", -1)]


def update_payment(db: Database, payment_id: str, payload: schemas.PaymentUpdate) -> dict:
    _get_payment_or_404(db, payment_id)
    db.payments.update_one({"id": payment_id}, {"$set": {"confirmed": payload.confirmed}})
    return _strip_mongo_id(_get_payment_or_404(db, payment_id))


def _apply_transfer(ledger: dict[tuple[str, str], float], debtor: str, creditor: str, amount: float) -> None:
    if debtor == creditor or amount <= 0:
        return
    ledger[(debtor, creditor)] = ledger.get((debtor, creditor), 0.0) + amount


def get_event_balances(db: Database, event_id: str) -> list[dict]:
    _get_event_or_404(db, event_id)
    receipts = [
        _strip_mongo_id(receipt)
        for receipt in db.receipts.find({"event_id": event_id})
    ]
    confirmed_payments = [
        _strip_mongo_id(payment)
        for payment in db.payments.find({"event_id": event_id, "confirmed": True})
    ]

    ledger: dict[tuple[str, str], float] = {}
    for receipt in receipts:
        payer_id = receipt["payer_id"]
        share_map = {item["id"]: item for item in receipt.get("share_items", [])}

        for item in receipt.get("items", []):
            cost = float(item["cost"])
            for share_id in item.get("share_items", []):
                share = share_map.get(share_id)
                if not share:
                    continue
                debitor_id = share["user_id"]
                amount = cost * float(share["share_value"])
                _apply_transfer(ledger, debitor_id, payer_id, amount)

    for payment in confirmed_payments:
        _apply_transfer(
            ledger,
            payment["receiver_id"],
            payment["sender_id"],
            float(payment["amount"]),
        )

    results: list[dict] = []
    processed_pairs: set[tuple[str, str]] = set()
    for debtor, creditor in list(ledger.keys()):
        if (debtor, creditor) in processed_pairs or (creditor, debtor) in processed_pairs:
            continue

        forward = ledger.get((debtor, creditor), 0.0)
        backward = ledger.get((creditor, debtor), 0.0)
        net = forward - backward

        if net > 1e-6:
            results.append(
                {
                    "event_id": event_id,
                    "debitor_id": debtor,
                    "creditor_id": creditor,
                    "amount": round(net, 2),
                }
            )
        elif net < -1e-6:
            results.append(
                {
                    "event_id": event_id,
                    "debitor_id": creditor,
                    "creditor_id": debtor,
                    "amount": round(-net, 2),
                }
            )

        processed_pairs.add((debtor, creditor))
        processed_pairs.add((creditor, debtor))

    return sorted(results, key=lambda row: (row["debitor_id"], row["creditor_id"]))


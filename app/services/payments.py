from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import observe_money_amount, record_domain_event, track_service_operation

from app.services.access import assert_event_access, assert_event_open, get_payment_or_404
from app.services.common import active_filter, new_uuid, record_audit_event, strip_mongo_id, utc_now
from app.services.common import money_to_storage, stored_money_to_kopecks
from app.services.idempotency import run_idempotent_create


def _payment_to_api(payment: dict) -> dict:
    cleaned = strip_mongo_id(payment)
    cleaned["amount_kopecks"] = stored_money_to_kopecks(cleaned, "amount_kopecks", "amount")
    cleaned.pop("amount", None)
    return cleaned


@track_service_operation("payments.create")
def create_payment(
    db: Database,
    event_id: str,
    payload: schemas.PaymentCreate,
    actor_user_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"events:{event_id}:payments",
        key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create=lambda: _create_payment(db, event_id, payload, actor_user_id),
    )


def _create_payment(
    db: Database, event_id: str, payload: schemas.PaymentCreate, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)
    sender_id = str(payload.sender_id)
    receiver_id = str(payload.receiver_id)

    if sender_id != actor_user_id:
        raise HTTPException(status_code=403, detail="sender_id must match the authenticated user.")

    if sender_id == receiver_id:
        raise HTTPException(status_code=400, detail="sender_id and receiver_id must differ.")

    if sender_id not in event["users"] or receiver_id not in event["users"]:
        raise HTTPException(
            status_code=400,
            detail="sender_id and receiver_id must belong to event users.",
        )

    payment = {
        "id": new_uuid(),
        "event_id": event_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount_kopecks": money_to_storage(payload.amount_kopecks),
        "confirmed": False,
        "created_at": utc_now(),
    }
    db.payments.insert_one(payment)
    record_domain_event("payments", "created")
    observe_money_amount("payment_amount", payload.amount_kopecks / 100)
    return _payment_to_api(payment)


@track_service_operation("payments.list")
def list_payments_by_event(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    query = active_filter({"event_id": event_id})
    total = db.payments.count_documents(query)
    cursor = db.payments.find(query).sort("created_at", -1).skip(offset).limit(limit)
    return {
        "items": [_payment_to_api(item) for item in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("payments.update")
def update_payment(
    db: Database, payment_id: str, payload: schemas.PaymentUpdate, actor_user_id: str
) -> dict:
    payment = get_payment_or_404(db, payment_id)
    event = assert_event_access(db, payment["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment["receiver_id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the payment receiver can update confirmation.",
        )
    db.payments.update_one({"id": payment_id}, {"$set": {"confirmed": payload.confirmed}})
    record_domain_event("payments", "confirmed" if payload.confirmed else "unconfirmed")
    record_audit_event(
        db,
        action="payment.confirmation_updated",
        resource_type="payment",
        resource_id=payment_id,
        actor_user_id=actor_user_id,
    )
    return _payment_to_api(get_payment_or_404(db, payment_id))


@track_service_operation("payments.delete")
def delete_payment(db: Database, payment_id: str, actor_user_id: str) -> None:
    payment = get_payment_or_404(db, payment_id)
    event = assert_event_access(db, payment["event_id"], actor_user_id)
    assert_event_open(event)

    if payment.get("confirmed"):
        raise HTTPException(status_code=409, detail="Confirmed payments cannot be deleted.")

    if actor_user_id not in {payment["sender_id"], payment["receiver_id"]}:
        raise HTTPException(
            status_code=403,
            detail="Only the payment sender or receiver can delete this payment.",
        )

    now = utc_now()
    db.payments.update_one(
        active_filter({"id": payment_id}),
        {"$set": {"deleted_at": now, "deleted_by": actor_user_id, "updated_at": now}},
    )
    record_domain_event("payments", "deleted")
    record_audit_event(
        db,
        action="payment.deleted",
        resource_type="payment",
        resource_id=payment_id,
        actor_user_id=actor_user_id,
    )

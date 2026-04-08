from fastapi import HTTPException
from pymongo.database import Database

from app import schemas

from app.services.access import assert_event_access, get_payment_or_404
from app.services.common import new_uuid, strip_mongo_id, utc_now


def create_payment(
    db: Database, event_id: str, payload: schemas.PaymentCreate, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
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
        "id": new_uuid(),
        "event_id": event_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount": payload.amount,
        "confirmed": False,
        "created_at": utc_now(),
    }
    db.payments.insert_one(payment)
    return payment


def list_payments_by_event(db: Database, event_id: str, actor_user_id: str) -> list[dict]:
    assert_event_access(db, event_id, actor_user_id)
    return [
        strip_mongo_id(item)
        for item in db.payments.find({"event_id": event_id}).sort("created_at", -1)
    ]


def update_payment(
    db: Database, payment_id: str, payload: schemas.PaymentUpdate, actor_user_id: str
) -> dict:
    payment = get_payment_or_404(db, payment_id)
    assert_event_access(db, payment["event_id"], actor_user_id)
    db.payments.update_one({"id": payment_id}, {"$set": {"confirmed": payload.confirmed}})
    return strip_mongo_id(get_payment_or_404(db, payment_id))

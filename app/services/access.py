from fastapi import HTTPException
from pymongo.database import Database


def get_user_or_404(db: Database, user_id: str) -> dict:
    user = db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")
    return user


def get_event_or_404(db: Database, event_id: str) -> dict:
    event = db.events.find_one({"id": event_id})
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")
    return event


def assert_event_member(db: Database, event_id: str, user_id: str) -> dict:
    event = get_event_or_404(db, event_id)
    if user_id not in event["users"]:
        raise HTTPException(
            status_code=403,
            detail="Not a member of this event.",
        )
    return event


def get_receipt_or_404(db: Database, receipt_id: str) -> dict:
    receipt = db.receipts.find_one({"id": receipt_id})
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found.")
    return receipt


def get_payment_or_404(db: Database, payment_id: str) -> dict:
    payment = db.payments.find_one({"id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found.")
    return payment

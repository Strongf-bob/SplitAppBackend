from fastapi import HTTPException
from pymongo.database import Database

from app.services.common import active_filter


def get_user_or_404(db: Database, user_id: str) -> dict:
    user = db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def get_event_or_404(db: Database, event_id: str) -> dict:
    event = db.events.find_one(active_filter({"id": event_id}))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


def active_event_memberships(db: Database, event_id: str) -> list[dict]:
    return list(
        db.event_memberships.find(
            {"event_id": event_id, "status": "active", "deleted_at": {"$exists": False}}
        ).sort("joined_at", 1)
    )


def active_event_user_ids(db: Database, event_id: str) -> list[str]:
    return [membership["user_id"] for membership in active_event_memberships(db, event_id)]


def assert_event_member(db: Database, event_id: str, user_id: str) -> dict:
    event = get_event_or_404(db, event_id)
    membership = db.event_memberships.find_one(
        {
            "event_id": event_id,
            "user_id": user_id,
            "status": "active",
            "deleted_at": {"$exists": False},
        }
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="Not a member of this event.",
        )
    event["users"] = active_event_user_ids(db, event_id)
    return event


def assert_event_access(db: Database, event_id: str, actor_user_id: str) -> dict:
    return assert_event_member(db, event_id, actor_user_id)


def assert_event_open(event: dict) -> None:
    if event.get("is_closed"):
        raise HTTPException(
            status_code=409,
            detail="Event is closed and cannot be modified.",
        )


def assert_event_creator(event: dict, actor_user_id: str) -> None:
    if actor_user_id != event["creator_id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the event creator can perform this action.",
        )


def get_receipt_or_404(db: Database, receipt_id: str) -> dict:
    receipt = db.receipts.find_one(active_filter({"id": receipt_id}))
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return receipt


def get_payment_or_404(db: Database, payment_id: str) -> dict:
    payment = db.payments.find_one(active_filter({"id": payment_id}))
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return payment

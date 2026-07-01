from decimal import Decimal, ROUND_HALF_UP

from pymongo.database import Database

from app.services.balances import get_event_balances
from app.services.common import active_filter, decimal_from_value, stored_money_to_kopecks


def _empty_bucket() -> dict:
    return {"owed_kopecks": 0, "receivable_kopecks": 0}


def _add_amount(
    bucket: dict, *, user_id: str, debtor_id: str, creditor_id: str, amount: int
) -> None:
    if amount <= 0 or debtor_id == creditor_id:
        return
    if user_id == debtor_id:
        bucket["owed_kopecks"] += amount
    if user_id == creditor_id:
        bucket["receivable_kopecks"] += amount


def _share_amounts(receipt: dict) -> dict[str, int]:
    share_by_id = {share["id"]: share for share in receipt.get("share_items", [])}
    amounts: dict[str, int] = {}
    for item in receipt.get("items", []):
        cost_kopecks = stored_money_to_kopecks(item, "cost_kopecks", "cost")
        for share_id in item.get("share_items", []):
            share = share_by_id.get(share_id)
            if not share:
                continue
            user_id = share["user_id"]
            amount = int(
                (Decimal(cost_kopecks) * decimal_from_value(share["share_value"])).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            amounts[user_id] = amounts.get(user_id, 0) + amount
    return amounts


def get_home_summary(db: Database, actor_user_id: str) -> dict:
    confirmed = _empty_bucket()
    pending = _empty_bucket()
    disputed = _empty_bucket()

    event_ids = [
        membership["event_id"]
        for membership in db.event_memberships.find(
            {"user_id": actor_user_id, "status": "active", "deleted_at": {"$exists": False}}
        )
    ]

    for event_id in event_ids:
        for row in get_event_balances(db, event_id, actor_user_id):
            _add_amount(
                confirmed,
                user_id=actor_user_id,
                debtor_id=row["debitor_id"],
                creditor_id=row["creditor_id"],
                amount=row["amount_kopecks"],
            )

    receipt_cache: dict[str, dict] = {}
    for review in db.receipt_share_reviews.find(active_filter({"event_id": {"$in": event_ids}})):
        if review.get("status") not in {"pending", "disputed"}:
            continue
        receipt = receipt_cache.get(review["receipt_id"])
        if receipt is None:
            receipt = db.receipts.find_one(active_filter({"id": review["receipt_id"]}))
            if receipt is None:
                continue
            receipt_cache[review["receipt_id"]] = receipt
        amount = _share_amounts(receipt).get(review["user_id"], 0)
        bucket = disputed if review["status"] == "disputed" else pending
        _add_amount(
            bucket,
            user_id=actor_user_id,
            debtor_id=review["user_id"],
            creditor_id=receipt["payer_id"],
            amount=amount,
        )

    for request in db.payment_requests.find(active_filter({"event_id": {"$in": event_ids}})):
        if request.get("status") not in {"requested", "paid", "disputed"}:
            continue
        bucket = disputed if request["status"] == "disputed" else pending
        _add_amount(
            bucket,
            user_id=actor_user_id,
            debtor_id=request["debtor_id"],
            creditor_id=request["creditor_id"],
            amount=stored_money_to_kopecks(request, "amount_kopecks", "amount"),
        )

    for payment in db.payments.find(
        active_filter(
            {
                "event_id": {"$in": event_ids},
                "status": "pending",
                "payment_request_id": {"$exists": False},
            }
        )
    ):
        _add_amount(
            pending,
            user_id=actor_user_id,
            debtor_id=payment["sender_id"],
            creditor_id=payment["receiver_id"],
            amount=stored_money_to_kopecks(payment, "amount_kopecks", "amount"),
        )

    return {"confirmed": confirmed, "pending": pending, "disputed": disputed}

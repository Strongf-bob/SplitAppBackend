import csv
from io import StringIO

from pymongo.database import Database

from app.services.access import assert_event_access
from app.services.balances import get_event_balances
from app.services.common import active_filter, stored_money_to_kopecks

RECEIPT_CATEGORIES = [
    "groceries",
    "restaurant",
    "transport",
    "housing",
    "entertainment",
    "travel",
    "utilities",
    "other",
]


def list_receipt_categories() -> list[str]:
    return RECEIPT_CATEGORIES


def build_event_csv_export(db: Database, event_id: str, actor_user_id: str) -> str:
    assert_event_access(db, event_id, actor_user_id)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "section",
            "id",
            "status",
            "debtor_id",
            "creditor_id",
            "sender_id",
            "receiver_id",
            "amount_kopecks",
            "title",
            "category",
        ]
    )

    for row in get_event_balances(db, event_id, actor_user_id):
        writer.writerow(
            [
                "debt",
                "",
                "",
                row["debitor_id"],
                row["creditor_id"],
                "",
                "",
                row["amount_kopecks"],
                "",
                "",
            ]
        )

    for receipt in db.receipts.find(active_filter({"event_id": event_id})).sort("created_at", 1):
        writer.writerow(
            [
                "receipt",
                receipt["id"],
                receipt.get("status", "confirmed"),
                "",
                "",
                "",
                "",
                stored_money_to_kopecks(receipt, "total_amount_kopecks", "total_amount"),
                receipt.get("title", ""),
                receipt.get("category") or "",
            ]
        )

    for payment in db.payments.find(active_filter({"event_id": event_id})).sort("created_at", 1):
        writer.writerow(
            [
                "payment",
                payment["id"],
                "confirmed" if payment.get("confirmed") else payment.get("status", "pending"),
                "",
                "",
                payment["sender_id"],
                payment["receiver_id"],
                stored_money_to_kopecks(payment, "amount_kopecks", "amount"),
                "",
                "",
            ]
        )

    return output.getvalue()

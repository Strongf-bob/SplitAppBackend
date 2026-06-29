from decimal import Decimal, ROUND_HALF_UP

from pymongo.database import Database

from app.core.monitoring import track_service_operation
from app.services.access import assert_event_access
from app.services.common import active_filter, decimal_from_value, stored_money_to_kopecks, strip_mongo_id


def _apply_transfer(
    ledger: dict[tuple[str, str], int], debtor: str, creditor: str, amount_kopecks: int
) -> None:
    if debtor == creditor or amount_kopecks <= 0:
        return
    ledger[(debtor, creditor)] = ledger.get((debtor, creditor), 0) + amount_kopecks


def _share_amount_kopecks(cost_kopecks: int, share_value: object) -> int:
    return int(
        (Decimal(cost_kopecks) * decimal_from_value(share_value)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


@track_service_operation("balances.get_event")
def get_event_balances(db: Database, event_id: str, actor_user_id: str) -> list[dict]:
    assert_event_access(db, event_id, actor_user_id)
    receipts = [
        strip_mongo_id(receipt)
        for receipt in db.receipts.find(
            active_filter(
                {
                    "event_id": event_id,
                    "$or": [{"status": "confirmed"}, {"status": {"$exists": False}}],
                }
            )
        )
    ]
    confirmed_payments = [
        strip_mongo_id(payment)
        for payment in db.payments.find(active_filter({"event_id": event_id, "confirmed": True}))
    ]

    ledger: dict[tuple[str, str], int] = {}
    for receipt in receipts:
        payer_id = receipt["payer_id"]
        share_map = {item["id"]: item for item in receipt.get("share_items", [])}

        for item in receipt.get("items", []):
            cost_kopecks = stored_money_to_kopecks(item, "cost_kopecks", "cost")
            for share_id in item.get("share_items", []):
                share = share_map.get(share_id)
                if not share:
                    continue
                debitor_id = share["user_id"]
                amount_kopecks = _share_amount_kopecks(cost_kopecks, share["share_value"])
                _apply_transfer(ledger, debitor_id, payer_id, amount_kopecks)

    for payment in confirmed_payments:
        _apply_transfer(
            ledger,
            payment["receiver_id"],
            payment["sender_id"],
            stored_money_to_kopecks(payment, "amount_kopecks", "amount"),
        )

    results: list[dict] = []
    processed_pairs: set[tuple[str, str]] = set()
    for debtor, creditor in list(ledger.keys()):
        if (debtor, creditor) in processed_pairs or (creditor, debtor) in processed_pairs:
            continue

        forward = ledger.get((debtor, creditor), 0)
        backward = ledger.get((creditor, debtor), 0)
        net = forward - backward

        if net > 0:
            results.append(
                {
                    "event_id": event_id,
                    "debitor_id": debtor,
                    "creditor_id": creditor,
                    "amount_kopecks": net,
                }
            )
        elif net < 0:
            results.append(
                {
                    "event_id": event_id,
                    "debitor_id": creditor,
                    "creditor_id": debtor,
                    "amount_kopecks": -net,
                }
            )

        processed_pairs.add((debtor, creditor))
        processed_pairs.add((creditor, debtor))

    return sorted(results, key=lambda row: (row["debitor_id"], row["creditor_id"]))

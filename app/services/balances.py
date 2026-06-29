from decimal import Decimal

from pymongo.database import Database

from app.core.monitoring import track_service_operation
from app.services.access import assert_event_access
from app.services.common import active_filter, decimal_from_value, money_round, strip_mongo_id


def _apply_transfer(
    ledger: dict[tuple[str, str], Decimal], debtor: str, creditor: str, amount: Decimal
) -> None:
    if debtor == creditor or amount <= 0:
        return
    ledger[(debtor, creditor)] = ledger.get((debtor, creditor), Decimal("0")) + amount


@track_service_operation("balances.get_event")
def get_event_balances(db: Database, event_id: str, actor_user_id: str) -> list[dict]:
    assert_event_access(db, event_id, actor_user_id)
    receipts = [
        strip_mongo_id(receipt)
        for receipt in db.receipts.find(active_filter({"event_id": event_id}))
    ]
    confirmed_payments = [
        strip_mongo_id(payment)
        for payment in db.payments.find(active_filter({"event_id": event_id, "confirmed": True}))
    ]

    ledger: dict[tuple[str, str], Decimal] = {}
    for receipt in receipts:
        payer_id = receipt["payer_id"]
        share_map = {item["id"]: item for item in receipt.get("share_items", [])}

        for item in receipt.get("items", []):
            cost = decimal_from_value(item["cost"])
            for share_id in item.get("share_items", []):
                share = share_map.get(share_id)
                if not share:
                    continue
                debitor_id = share["user_id"]
                amount = cost * decimal_from_value(share["share_value"])
                _apply_transfer(ledger, debitor_id, payer_id, amount)

    for payment in confirmed_payments:
        _apply_transfer(
            ledger,
            payment["receiver_id"],
            payment["sender_id"],
            decimal_from_value(payment["amount"]),
        )

    results: list[dict] = []
    processed_pairs: set[tuple[str, str]] = set()
    for debtor, creditor in list(ledger.keys()):
        if (debtor, creditor) in processed_pairs or (creditor, debtor) in processed_pairs:
            continue

        forward = ledger.get((debtor, creditor), Decimal("0"))
        backward = ledger.get((creditor, debtor), Decimal("0"))
        net = forward - backward

        if net > 0:
            results.append(
                {
                    "event_id": event_id,
                    "debitor_id": debtor,
                    "creditor_id": creditor,
                    "amount": money_round(net),
                }
            )
        elif net < 0:
            results.append(
                {
                    "event_id": event_id,
                    "debitor_id": creditor,
                    "creditor_id": debtor,
                    "amount": money_round(-net),
                }
            )

        processed_pairs.add((debtor, creditor))
        processed_pairs.add((creditor, debtor))

    return sorted(results, key=lambda row: (row["debitor_id"], row["creditor_id"]))

from typing import Literal

from pymongo.database import Database

from app.core.monitoring import track_service_operation
from app.services.balances import get_event_balance_explanations
from app.services.settlement_algorithm import build_settlement_edges


def _source_participant_ids(raw_debts: list[dict]) -> list[str]:
    participant_ids = {
        user_id for row in raw_debts for user_id in (row["debitor_id"], row["creditor_id"])
    }
    return sorted(participant_ids)


def _net_positions(raw_debts: list[dict]) -> list[dict]:
    positions: dict[str, int] = {}
    for row in raw_debts:
        amount_kopecks = row["amount_kopecks"]
        debtor_id = row["debitor_id"]
        creditor_id = row["creditor_id"]
        positions[debtor_id] = positions.get(debtor_id, 0) - amount_kopecks
        positions[creditor_id] = positions.get(creditor_id, 0) + amount_kopecks

    debtors: list[dict[str, str | int | Literal["owes", "receives"]]] = [
        {"user_id": user_id, "direction": "owes", "amount_kopecks": -amount}
        for user_id, amount in positions.items()
        if amount < 0
    ]
    creditors: list[dict[str, str | int | Literal["owes", "receives"]]] = [
        {"user_id": user_id, "direction": "receives", "amount_kopecks": amount}
        for user_id, amount in positions.items()
        if amount > 0
    ]

    debtors.sort(key=lambda item: (-int(item["amount_kopecks"]), str(item["user_id"])))
    creditors.sort(key=lambda item: (-int(item["amount_kopecks"]), str(item["user_id"])))
    return debtors + creditors


@track_service_operation("settlements.preview")
def get_settlement_preview(db: Database, event_id: str, actor_user_id: str) -> dict:
    raw_debts = get_event_balance_explanations(db, event_id, actor_user_id)
    recommended_edges = build_settlement_edges(raw_debts)

    return {
        "event_id": event_id,
        "raw_debts": raw_debts,
        "net_positions": _net_positions(raw_debts),
        "recommended_transfers": [
            {
                "debtor_id": row["debitor_id"],
                "creditor_id": row["creditor_id"],
                "amount_kopecks": row["amount_kopecks"],
            }
            for row in recommended_edges
        ],
        "source_participant_ids": _source_participant_ids(raw_debts),
        "original_transfer_count": len(raw_debts),
        "recommended_transfer_count": len(recommended_edges),
        "original_gross_kopecks": sum(row["amount_kopecks"] for row in raw_debts),
        "recommended_total_kopecks": sum(row["amount_kopecks"] for row in recommended_edges),
        "transfer_count_reduced": len(recommended_edges) < len(raw_debts),
    }

def build_settlement_edges(balance_rows: list[dict]) -> list[dict]:
    if not balance_rows:
        return []

    event_id: str | None = None
    net_positions: dict[str, int] = {}

    for index, row in enumerate(balance_rows):
        missing_keys = {
            key
            for key in ("event_id", "debitor_id", "creditor_id", "amount_kopecks")
            if key not in row
        }
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(f"Balance row {index} is missing required keys: {missing}")

        row_event_id = row["event_id"]
        debtor_id = row["debitor_id"]
        creditor_id = row["creditor_id"]
        amount_kopecks = row["amount_kopecks"]

        if event_id is None:
            event_id = row_event_id
        elif row_event_id != event_id:
            raise ValueError("Balance rows must belong to a single event")

        if debtor_id == creditor_id:
            raise ValueError("Balance row cannot use the same user as debtor and creditor")
        if (
            not isinstance(amount_kopecks, int)
            or isinstance(amount_kopecks, bool)
            or amount_kopecks <= 0
        ):
            raise ValueError("Balance row amount_kopecks must be a positive integer")

        net_positions[debtor_id] = net_positions.get(debtor_id, 0) - amount_kopecks
        net_positions[creditor_id] = net_positions.get(creditor_id, 0) + amount_kopecks

    debtors = sorted(
        [[user_id, -amount] for user_id, amount in net_positions.items() if amount < 0],
        key=lambda item: (-item[1], item[0]),
    )
    creditors = sorted(
        [[user_id, amount] for user_id, amount in net_positions.items() if amount > 0],
        key=lambda item: (-item[1], item[0]),
    )

    edges: list[dict] = []
    debtor_index = 0
    creditor_index = 0

    while debtor_index < len(debtors) and creditor_index < len(creditors):
        debtor_id, debt_kopecks = debtors[debtor_index]
        creditor_id, credit_kopecks = creditors[creditor_index]
        transfer_kopecks = min(debt_kopecks, credit_kopecks)

        edges.append(
            {
                "event_id": event_id,
                "debitor_id": debtor_id,
                "creditor_id": creditor_id,
                "amount_kopecks": transfer_kopecks,
            }
        )

        debtors[debtor_index][1] -= transfer_kopecks
        creditors[creditor_index][1] -= transfer_kopecks

        if debtors[debtor_index][1] == 0:
            debtor_index += 1
        if creditors[creditor_index][1] == 0:
            creditor_index += 1

    if debtor_index != len(debtors) or creditor_index != len(creditors):
        raise ValueError("Failed to conserve balance rows during settlement simplification")

    return sorted(edges, key=lambda row: (row["debitor_id"], row["creditor_id"]))

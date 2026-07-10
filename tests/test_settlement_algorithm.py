import importlib

import pytest


def build_settlement_edges(balance_rows: list[dict]) -> list[dict]:
    try:
        module = importlib.import_module("app.services.settlement_algorithm")
    except ModuleNotFoundError:
        pytest.fail("app.services.settlement_algorithm module is missing")
    return module.build_settlement_edges(balance_rows)


def _net_positions(rows: list[dict]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for row in rows:
        amount = row["amount_kopecks"]
        debtor = row["debitor_id"]
        creditor = row["creditor_id"]
        positions[debtor] = positions.get(debtor, 0) - amount
        positions[creditor] = positions.get(creditor, 0) + amount
    return {user_id: amount for user_id, amount in positions.items() if amount != 0}


def test_build_settlement_edges_eliminates_three_person_cycle():
    rows = [
        {
            "event_id": "event-1",
            "debitor_id": "katya",
            "creditor_id": "vanya",
            "amount_kopecks": 500,
        },
        {
            "event_id": "event-1",
            "debitor_id": "petya",
            "creditor_id": "katya",
            "amount_kopecks": 500,
        },
        {
            "event_id": "event-1",
            "debitor_id": "vanya",
            "creditor_id": "petya",
            "amount_kopecks": 500,
        },
    ]

    assert build_settlement_edges(rows) == []


def test_build_settlement_edges_is_deterministic_for_equal_ties():
    rows = [
        {
            "event_id": "event-1",
            "debitor_id": "anna",
            "creditor_id": "xenia",
            "amount_kopecks": 250,
        },
        {
            "event_id": "event-1",
            "debitor_id": "anna",
            "creditor_id": "yulia",
            "amount_kopecks": 250,
        },
        {
            "event_id": "event-1",
            "debitor_id": "boris",
            "creditor_id": "xenia",
            "amount_kopecks": 250,
        },
        {
            "event_id": "event-1",
            "debitor_id": "boris",
            "creditor_id": "yulia",
            "amount_kopecks": 250,
        },
    ]

    assert build_settlement_edges(rows) == [
        {
            "event_id": "event-1",
            "debitor_id": "anna",
            "creditor_id": "xenia",
            "amount_kopecks": 500,
        },
        {
            "event_id": "event-1",
            "debitor_id": "boris",
            "creditor_id": "yulia",
            "amount_kopecks": 500,
        },
    ]


def test_build_settlement_edges_preserves_net_positions_and_money_conservation():
    rows = [
        {
            "event_id": "event-1",
            "debitor_id": "anna",
            "creditor_id": "maria",
            "amount_kopecks": 400,
        },
        {
            "event_id": "event-1",
            "debitor_id": "anna",
            "creditor_id": "nina",
            "amount_kopecks": 100,
        },
        {
            "event_id": "event-1",
            "debitor_id": "boris",
            "creditor_id": "maria",
            "amount_kopecks": 150,
        },
        {
            "event_id": "event-1",
            "debitor_id": "nina",
            "creditor_id": "boris",
            "amount_kopecks": 50,
        },
    ]

    simplified = build_settlement_edges(rows)

    assert sum(row["amount_kopecks"] for row in simplified) == 600
    assert all(row["amount_kopecks"] > 0 for row in simplified)
    assert all(row["debitor_id"] != row["creditor_id"] for row in simplified)
    assert _net_positions(simplified) == _net_positions(rows)


def test_build_settlement_edges_returns_empty_list_for_empty_rows():
    assert build_settlement_edges([]) == []


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {
                    "event_id": "event-1",
                    "debitor_id": "anna",
                    "creditor_id": "anna",
                    "amount_kopecks": 10,
                }
            ],
            "same user",
        ),
        (
            [
                {
                    "event_id": "event-1",
                    "debitor_id": "anna",
                    "creditor_id": "boris",
                    "amount_kopecks": 0,
                }
            ],
            "positive integer",
        ),
        (
            [
                {
                    "event_id": "event-1",
                    "debitor_id": "anna",
                    "creditor_id": "boris",
                    "amount_kopecks": 10,
                },
                {
                    "event_id": "event-2",
                    "debitor_id": "boris",
                    "creditor_id": "maria",
                    "amount_kopecks": 10,
                },
            ],
            "single event",
        ),
    ],
)
def test_build_settlement_edges_rejects_invalid_rows(rows, message):
    with pytest.raises(ValueError, match=message):
        build_settlement_edges(rows)

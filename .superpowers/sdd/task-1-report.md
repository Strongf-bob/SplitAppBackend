# Task 1 Report: Globally simplified intra-event balances

## Changed files
- `app/services/settlement_algorithm.py`
- `app/services/balances.py`
- `app/services/__init__.py`
- `tests/test_settlement_algorithm.py`
- `tests/test_services.py`

## RED commands and expected failures
- `./.venv/bin/python -m pytest -q tests/test_settlement_algorithm.py`
  - Result: 7 failed
  - Expected failures observed:
    - `app.services.settlement_algorithm module is missing`
    - no deterministic global simplification implementation existed yet
- `./.venv/bin/python -m pytest -q tests/test_services.py -k 'event_raw_balances_preserve_pairwise_edges_while_event_balances_are_globally_simplified or confirmed_payment_on_simplified_edge_reduces_global_net_positions'`
  - Result: 2 failed
  - Expected failures observed:
    - `app.services.balances` had no `get_event_raw_balances`
    - `get_event_balances` still returned raw pairwise rows instead of globally simplified rows

## GREEN commands and results
- `./.venv/bin/python -m pytest -q tests/test_settlement_algorithm.py`
  - Result: 7 passed
- `./.venv/bin/python -m pytest -q tests/test_services.py -k 'event_raw_balances_preserve_pairwise_edges_while_event_balances_are_globally_simplified or confirmed_payment_on_simplified_edge_reduces_global_net_positions'`
  - Result: 2 passed, 91 deselected
- `./.venv/bin/python -m pytest -q tests/test_services.py`
  - Result: 93 passed
- `make lint`
  - Result: passed
- `make format-check`
  - Result: initially failed because two files needed formatting; after `./.venv/bin/python -m ruff format app/services/settlement_algorithm.py tests/test_services.py` it passed
- `make test`
  - Result: 192 passed, 1 skipped

## Commit hash
- `dfac43fcaf378f0ae88544259379dadb879629e6`

## Self-review
- Preserved existing pairwise receipt/payment ledger math as `get_event_raw_balances`.
- Kept `get_event_balance_explanations` on the raw pairwise path so receipt/payment provenance stays explainable.
- Added a pure deterministic settlement matcher with validation for invalid rows, cycle elimination, tie determinism, and money conservation.
- Added a regression proving that a confirmed payment along a simplified edge reduces the global net position even when the original raw graph was a chain through an intermediary.
- Touched only the balance/settlement files requested for Task 1 plus the requested task report.

## Concerns
- None.

## Follow-up fix after review
- Important review finding fixed: `docs/wiki/API-Reference.md` no longer claims `/api/events/{id}/balances/explain` returns the same simplified debts as `/balances`.
- Updated wording:
  - `/api/events/{id}/balances` documents globally simplified debtor-creditor edges.
  - `/api/events/{id}/balances/explain` documents raw pairwise obligations with receipt/payment contributions for audit/explanation.
- Focused verification for this fix:
  - `rg -n "same simplified|simplified debts|raw pairwise obligations|globally simplified debtor-creditor edges|audit/explanation" docs/wiki/API-Reference.md docs/wiki openapi.yaml app/routers/events.py`
    - Result: only `docs/wiki/API-Reference.md:136-137` matched the new corrected wording; no same exact stale claim remained nearby in the searched docs/router scope.
  - `./.venv/bin/python -m pytest -q tests/test_app_config.py`
    - Result: 33 passed

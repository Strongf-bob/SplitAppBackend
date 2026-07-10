# Task 4 Report: Settlement payment request materialization

## RED

- Added failing service tests for persisted plan edges, execute authorization/state guards, stale approved execution, forged edge rejection, partial materialization retry, duplicate protection across same/different actor idempotency keys, exact payment request provenance, debtor mark-paid, receiver confirm/reject, one-edge completion, multi-edge partial/completed progress, rejected payment visibility, and public payment-request authorization/forge resistance.
- Added failing API/OpenAPI/index tests for `POST /api/settlement-plans/{id}/execute`, required `Idempotency-Key`, `SettlementPlan.edges`, extended plan status enum, and the unique sparse `(settlement_plan_id, settlement_edge_id)` index.
- Verified RED:
  - `.venv/bin/python -m pytest tests/test_services.py -k 'settlement_execute or settlement_one_edge or settlement_multi_edge or settlement_rejected_payment or settlement_public_payment_request_authorization_rule_is_unchanged or settlement_plan_create_persists_server_edges' -q`
    - Expected failures: missing `edges`, missing `execute_settlement_plan`, missing internal materialization helper.
  - `.venv/bin/python -m pytest tests/test_app_config.py -k 'settlement_plan_execute_endpoint or openapi_exposes_settlement_plan_contract or payment_requests_have_unique_sparse_settlement_edge_index' -q`
    - Expected failures: execute route returned 404, `SettlementPlanEdge` missing, unique sparse index missing.

## GREEN

- Persisted server-generated settlement `edges` on newly created plans while keeping preview transfers edge-id-free.
- Added guarded execution for approved plans:
  - current event member required;
  - event must be open;
  - approved snapshot is recomputed once before transition;
  - stale approved plans transition to `stale`;
  - retries from `executing` / `partially_settled` / `completed` skip original snapshot comparison.
- Added idempotent/resumable materialization of one payment request per stored edge via an internal helper that validates the loaded plan and exact stored edge, never client-supplied parties or amount.
- Added generated payment request provenance:
  - `origin="settlement_plan"`;
  - `settlement_plan_id`;
  - `settlement_edge_id`;
  - `created_by` as executor;
  - optimized settlement note.
- Added lazy progress derivation for get/list plus refresh after linked payment confirmation/rejection:
  - `executing` for linked requests without confirmed payments;
  - `partially_settled` when at least one but not all edge requests are confirmed;
  - `completed` only when all linked edge requests are confirmed;
  - rejected/disputed/cancelled request statuses remain visible and do not auto-complete the plan.
- Added unique sparse compound index on `payment_requests(settlement_plan_id, settlement_edge_id)`.
- Added API schema and OpenAPI sync for execute endpoint, plan edges, and extended statuses.

## Verification

- Focused service tests:
  - `.venv/bin/python -m pytest tests/test_services.py -k 'settlement_execute or settlement_one_edge or settlement_multi_edge or settlement_rejected_payment or settlement_public_payment_request_authorization_rule_is_unchanged or settlement_plan_create_persists_server_edges' -q`
  - Result: `11 passed, 115 deselected`
- Focused API/OpenAPI/index tests:
  - `.venv/bin/python -m pytest tests/test_app_config.py -k 'settlement_plan_execute_endpoint or openapi_exposes_settlement_plan_contract or payment_requests_have_unique_sparse_settlement_edge_index' -q`
  - Result: `3 passed, 36 deselected`
- Full services/app_config:
  - `.venv/bin/python -m pytest tests/test_services.py tests/test_app_config.py -q`
  - Result: `165 passed, 1 warning`
- Format:
  - `make format-check`
  - Result: `63 files already formatted`
- Lint:
  - `make lint`
  - Result: `All checks passed!`
- Full test suite:
  - `make test`
  - Result: `231 passed, 1 skipped, 1 warning`
- OpenAPI sync:
  - runtime `app.openapi()` JSON compared to `openapi.yaml`
  - Result: `openapi-sync-ok`
- Whitespace:
  - `git diff --check`
  - Result: clean

## Commit

- Intended Conventional Commit: `feat(settlement): create unique approved payment requests`

## Self-review

- Scope stayed backend-only; no PWA files or docs were changed except the requested OpenAPI contract and this Task 4 report.
- Public payment request authorization remains unchanged: ordinary creation still requires `creditor_id == actor`, and forged settlement provenance fields in public payloads are not persisted.
- Execution does not create payments or confirm money; debtor mark-paid and receiver confirm/reject remain the only money lifecycle path.
- Duplicate protection is layered: service find-or-create plus a unique sparse compound index, with no duplicate audit on retries.
- Partial failures are retryable because the plan transitions to `executing` before per-edge materialization and successful edges are linked before later failures propagate.
- External reviewer subagent was not available in this Codex session, so the review was performed manually against the Task 4 brief and diff.

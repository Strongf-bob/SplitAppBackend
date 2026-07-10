# Task 5 report

## Scope

- Synced settlement documentation with the actual backend contract in code and `openapi.yaml`.
- Touched only owned documentation files:
  - `docs/wiki/API-Reference.md`
  - `docs/wiki/Domain-Flows.md`
  - `docs/wiki/Data-Model.md`
  - `docs/p0-safety-flows.md`
- Did not change backend code or regenerate `openapi.yaml`, because the runtime contract already matched the checked-in file.

## What was corrected

- Clarified that `GET /api/events/{id}/balances` returns globally simplified edges.
- Clarified that `GET /api/events/{id}/balances/explain` returns raw pairwise obligations with receipt/payment contributions.
- Documented settlement preview and plan endpoints with exact paths and lifecycle states.
- Documented closed-event read behavior for settlement preview and plan reads, plus open-event requirements for create/execute.
- Documented snapshot, 24h TTL, all-source-participant approval, idempotent execute/create, and settlement edge provenance.
- Corrected payment flow wording to `mark-paid` -> receiver `confirm`, with balances changing only on confirmed payments.
- Replaced stale `PATCH /api/payments/{id}` primary-flow wording in domain docs with the current explicit confirm flow.

## Verification

- Relevant service tests:
  - `.venv/bin/python -m pytest tests/test_services.py -k "balance or settlement"`
- Relevant API/OpenAPI tests:
  - `.venv/bin/python -m pytest tests/test_app_config.py -k "settlement or openapi"`
- Repo checks:
  - `make lint`
  - `make format-check`
  - `app.openapi()` vs `openapi.yaml` -> match
  - `git diff --check`

## Branch / commit

- Branch: `strongf/intra-event-settlement`
- Commit hash: reported in the task handoff after commit creation.

## Out of scope

- Frontend/PWA/iOS settlement UX changes.
- Backend behavior changes.
- OpenAPI regeneration without an actual runtime mismatch.

## Concerns

- No known backend contract mismatch after verification.

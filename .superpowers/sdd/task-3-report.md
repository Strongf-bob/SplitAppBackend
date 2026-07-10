# Task 3 Report: Snapshot-backed settlement plans

## RED

- Added service-level tests first for persisted canonical snapshots, idempotent replay, duplicate active plan guard, rejection release, required approver approval flow, stale source detection, expiry transition, and paginated list behavior.
- Observed RED:
  - `.venv/bin/pytest tests/test_services.py -k 'settlement_plan or settlement_preview' -q`
  - Result: 7 failed, 3 passed; failures were missing `create_settlement_plan` and related service functions.
- Added API/OpenAPI tests first for `Idempotency-Key`, create/list/get/approve/reject endpoints, hidden internal snapshot fields, reject reason bounds, and OpenAPI schemas.
- Observed RED:
  - `.venv/bin/pytest tests/test_app_config.py -k 'settlement_plan' -q`
  - Result: 2 failed; route returned 404 and `SettlementPlan` schema was missing.

## GREEN

- Implemented persisted settlement plans backed by canonical financial snapshots.
- Added `greedy-net-v1` algorithm version, 24-hour pending TTL, server-side expiry transition, stale transition on source or active-membership mismatch before action, required approver approvals, rejection, idempotent repeated approval, and duplicate active snapshot guard.
- Added sparse unique `active_key` index and released it on stale/rejected/expired terminal states.
- Exposed:
  - `POST /api/events/{id}/settlement-plans`
  - `GET /api/events/{id}/settlement-plans`
  - `GET /api/settlement-plans/{id}`
  - `POST /api/settlement-plans/{id}/approve`
  - `POST /api/settlement-plans/{id}/reject`
- Regenerated `openapi.yaml` from runtime `app.openapi()` and verified sync.

## Files

- `app/services/settlements.py`
- `app/services/indexes.py`
- `app/services/__init__.py`
- `app/routers/events.py`
- `app/schemas.py`
- `tests/test_services.py`
- `tests/test_app_config.py`
- `openapi.yaml`

## Verification

- `.venv/bin/pytest tests/test_services.py -k 'settlement_plan or settlement_preview' -q` -> 10 passed.
- `.venv/bin/pytest tests/test_app_config.py -k 'settlement_plan' -q` -> 2 passed, 1 existing Starlette deprecation warning.
- `.venv/bin/pytest tests/test_services.py -q` -> 103 passed.
- `.venv/bin/pytest tests/test_app_config.py -q` -> 37 passed, 1 existing Starlette deprecation warning.
- `make lint` -> All checks passed.
- `make format-check` -> 63 files already formatted.
- `make test` -> 206 passed, 1 skipped, 1 existing Starlette deprecation warning.
- Runtime OpenAPI comparison -> `openapi_sync True`, 77 runtime paths, 77 file paths.

## Commit

- Commit message: `feat(settlement): add snapshot plans and participant approvals`
- Final commit SHA is reported in the handoff after commit creation.

## Self-review and concerns

- No execute/payment-request generation was implemented.
- PWA files were not touched.
- Internal `canonical_snapshot`, `snapshot_hash`, and `active_key` are stored for server validation and hidden from API responses.
- Required approvers are the preview source participant IDs, so source graph intermediaries with net-zero positions still have to approve.
- `approved` plans intentionally keep `active_key`; only stale/rejected/expired terminal states release it, matching the Task 3 guard requirement.

## Review fix evidence: CHANGES_REQUIRED follow-up

### RED

- Added regressions for lost interleaved approvals, audit/domain event recording, stale-before-old-approver ordering, approve/reject post-write snapshot TOCTOU, expiry/rejection/stale exact-once events, and OpenAPI status enum.
- Observed RED:
  - `.venv/bin/pytest tests/test_services.py -k 'settlement_plan' -q`
  - Result: 10 failed, 6 passed; failures covered missing `record_domain_event`, lost interleaved approval, stale check returning 403 before stale transition, approve/reject TOCTOU not marking stale, and exact-once event gaps.
- Observed OpenAPI RED:
  - `.venv/bin/pytest tests/test_app_config.py -k 'settlement_plan_contract' -q`
  - Result: 1 failed; `SettlementPlan.status` had no enum in OpenAPI.

### GREEN

- Replaced whole-array approval writes with guarded atomic `$push` using `status=pending` and `approvals.user_id != actor`, with idempotent reread handling for repeated approvals.
- Added pre-check and immediate post-write canonical snapshot validation for approve/reject with `last_action_id` markers; TOCTOU mutations transition the just-mutated plan to `stale`, release `active_key`, and return 409.
- Moved expiry and stale detection before required-approver checks after current event access.
- Added audit/domain events for create, each new approval, approved, rejected, stale, and expired; idempotent replay/repeated approval do not duplicate records.
- Changed `SettlementPlan.status` to a literal enum and regenerated `openapi.yaml`.
- Kept execute/payment requests and PWA out of scope.

### Verification after review fixes

- `.venv/bin/pytest tests/test_services.py -k 'settlement_plan' -q` -> 16 passed.
- `.venv/bin/pytest tests/test_app_config.py -k 'settlement_plan' -q` -> 2 passed, 1 existing Starlette deprecation warning.
- `.venv/bin/pytest tests/test_services.py -q` -> 112 passed.
- `.venv/bin/pytest tests/test_app_config.py -q` -> 37 passed, 1 existing Starlette deprecation warning.
- `make lint` -> All checks passed.
- `make format-check` -> 63 files already formatted.
- `make test` -> 215 passed, 1 skipped, 1 existing Starlette deprecation warning.
- Runtime OpenAPI comparison -> `openapi_sync True`, 77 runtime paths, 77 file paths.

### Follow-up commit

- Commit message: `fix(settlement): harden plan approvals and stale transitions`
- Final commit SHA is reported in the handoff after commit creation.

## Re-review fix evidence: post-write actor membership removal

### RED

- Added regressions where the acting approver/rejecter is removed from event membership after initial `assert_event_access` but before lifecycle post-write snapshot validation.
- Added explicit coverage that public settlement preview and balance explain remain membership-protected for non-members.
- Observed RED:
  - `.venv/bin/pytest tests/test_services.py -k 'actor_removed_during_post_validation or balance_explain_requires_event_membership or settlement_preview_requires_event_membership' -q`
  - Result: 2 failed, 2 passed; approval/rejection post-validation raised 403 from the public balance path instead of returning 409 and marking the plan stale.

### GREEN

- Added private `_get_event_balance_explanations_unchecked` in `app/services/balances.py`.
- Added private `_build_settlement_preview` and `_get_settlement_preview_unchecked` in `app/services/settlements.py`.
- Changed lifecycle snapshot recomputation to use the private unchecked preview path after the initial access check, while public `get_event_balance_explanations` and `get_settlement_preview` still enforce membership.
- Actor removal during approve/reject post-validation now produces stale transition, releases `active_key`, records stale audit/domain event once, and returns 409 rather than leaving the plan approved/rejected or returning 403.

### Verification after re-review fix

- `.venv/bin/pytest tests/test_services.py -k 'actor_removed_during_post_validation or balance_explain_requires_event_membership or settlement_preview_requires_event_membership' -q` -> 4 passed.
- `.venv/bin/pytest tests/test_services.py -k 'settlement_plan or balance_explain_requires_event_membership or settlement_preview_requires_event_membership' -q` -> 20 passed.
- `.venv/bin/pytest tests/test_app_config.py -k 'settlement_plan' -q` -> 2 passed, 1 existing Starlette deprecation warning.
- `.venv/bin/pytest tests/test_services.py -q` -> 115 passed.
- `.venv/bin/pytest tests/test_app_config.py -q` -> 37 passed, 1 existing Starlette deprecation warning.
- `make lint` -> All checks passed.
- `make format-check` -> 63 files already formatted.
- `make test` -> 218 passed, 1 skipped, 1 existing Starlette deprecation warning.
- Runtime OpenAPI comparison -> `openapi_sync True`, 77 runtime paths, 77 file paths.

### Re-review commit

- Commit message: `fix(settlement): decouple snapshot validation from actor membership`
- Final commit SHA is reported in the handoff after commit creation.

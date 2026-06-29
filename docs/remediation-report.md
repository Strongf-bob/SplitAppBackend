# SplitAppBackend Remediation Report

Date: 2026-06-29

## Backend Work Completed
- Added repository agent rules and a project security baseline:
  - `8ded172 docs(security): add Codex operating baseline`
- Added backend regression infrastructure:
  - `6904fab test(backend): add pytest regression harness`
- Fixed event/payment authorization and closed-event guards:
  - `9cedd8c fix(events): block financial mutations for closed events`
  - `4f868a1 fix(events): delete events transactionally`
  - `3783e07 fix(payments): restrict payment confirmation to receivers`
- Closed auth/API gaps:
  - `a71b322 fix(auth): add refresh token rotation grace period`
  - `227ee30 feat(payments): add payment deletion endpoint`
  - `ba1a8be feat(receipts): add receipt detail endpoint`
  - `1d9c162 fix(api): configure explicit CORS origins`
- Added profile, storage lifecycle, and audit behavior:
  - `ac177f5 feat(users): add current-user profile updates`
  - `fb7820c feat(receipts): add receipt image deletion and presigned URLs`
  - `ee19e9e fix(data): soft-delete records with audit trail`
- Added operational hardening:
  - `2f9602f feat(logging): add structured request logging`
  - `f7ffc4c feat(monitoring): expose metrics and optional error reporting`
  - `9d1ca93 build(deploy): add systemd deployment path`
  - `f070de9 build(lint): add Ruff lint and format checks`

## Branches Pushed
- `strongf/docs-security-baseline`
- `strongf/backend-test-foundation`
- `strongf/backend-event-payment-guards`
- `strongf/backend-auth-api-gaps`
- `strongf/backend-profile-storage-audit`
- `strongf/backend-ops-hardening`
- `strongf/backend-remediation-report`

## Verification
- `make test`: 22 passed, 4 warnings.
- `make lint`: all checks passed.
- Warnings are from `fastapi.testclient` deprecation and short test-only JWT secret length.

## Remaining Frontend Work
These items belong to `/Users/strongf/Developer/SplitApp Yandex/SplitApp` and were intentionally not changed in this backend series:

- Load debts in `FriendsView` from backend balances/payments instead of leaving them empty.
- Implement real `settleDebt()` network call using backend payment endpoints.
- Wire receipt swipe-delete to `DELETE /api/receipts/{id}`.
- Connect `LocalFriendsStore` to `FriendsViewModel` or remove it if the server is the source of truth.
- Improve offline indication beyond a single warning.
- Remove the dead `.swift` file with a dot-only name.
- Either use the CoreData `Payment` mapping or remove unused persistence code.
- Normalize server error presentation instead of showing raw alerts.
- Add frontend pagination once backend pagination contracts are designed.

## Notes
- The backend still does not implement pagination for existing list endpoints. That should be designed as a separate API contract change because it affects iOS data flows.
- MongoDB transactional event deletion requires transaction support in the deployed MongoDB topology.
- `/api/metrics` is part of the backend API and should be protected by deployment/network policy if the service is publicly reachable.

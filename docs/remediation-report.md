# SplitAppBackend Remediation Report

Date: 2026-06-30

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
- Added follow-up critical authorization, money, and storage fixes:
  - `991f607 fix(events): restrict event management to creators`
  - `94f33eb fix(payments): prevent sender impersonation`
  - `d7d44e1 fix(users): limit user listing to visible participants`
  - `ec18396 fix(money): use Decimal for monetary calculations`
  - `9dff159 fix(receipts): keep receipt images private in S3`
- Added backend v2 product flows:
  - `2c68bb0 refactor(money): store monetary values in kopecks`
  - `9687e84 feat(api): add idempotency for financial create endpoints`
  - `f2f58be feat(events): model event memberships with roles`
  - `e0e6658 feat(events): add invite token flow`
  - `02e3874 feat(receipts): require confirmation before balances`
  - `ce7b266 fix(receipts): validate item allocations against memberships`
  - `75f7665 feat(balances): explain simplified event debts`
  - `e41a70a feat(payments): add request and confirmation workflow`

## Branches Pushed
- `strongf/docs-security-baseline`
- `strongf/backend-test-foundation`
- `strongf/backend-event-payment-guards`
- `strongf/backend-auth-api-gaps`
- `strongf/backend-profile-storage-audit`
- `strongf/backend-ops-hardening`
- `strongf/backend-remediation-report`
- `strongf/backend-critical-auth-money-storage-fixes`
- `strongf/backend-v2-money-members-receipts-debts`

## Verification
- `make test`: 59 passed, 4 warnings.
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
- Update frontend list decoders and pagination UI for the backend `items`/`limit`/`offset`/`total` envelope.

## Notes
- Backend pagination is implemented for `GET /api/events`, `GET /api/users`, `GET /api/events/{id}/receipts`, and `GET /api/events/{id}/payments`; frontend list clients still need to consume the paginated response envelope.
- MongoDB transactional event deletion requires transaction support in the deployed MongoDB topology.
- `/api/metrics` is part of the backend API and should be protected by deployment/network policy if the service is publicly reachable.
- `GET /api/users` now returns only the current user and users sharing an active event with the caller, not the whole user table.
- New receipt, payment, and balance money values use integer kopecks in API and MongoDB. Legacy decimal-string records are still read into kopecks during rollout.
- Receipt image uploads no longer request public object ACLs. Clients should use the presigned URL endpoint for temporary read access.
- Event authorization now uses `event_memberships` with `creator` and `member` roles.
- Invite link/QR backend support is implemented with token preview, accept, and revoke endpoints.
- New receipts start as `draft` and affect balances only after `POST /api/receipts/{id}/confirm`.
- Balance explanation and payment request flows are backend-supported; frontend integration remains out of scope for this backend branch.

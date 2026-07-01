# SplitAppBackend Remediation Report

Дата: 2026-06-30

## Что Сделано В Backend

- Добавлены repository agent rules и project security baseline:
  - `8ded172 docs(security): add Codex operating baseline`
- Добавлена backend regression infrastructure:
  - `6904fab test(backend): add pytest regression harness`
- Исправлены event/payment authorization и closed-event guards:
  - `9cedd8c fix(events): block financial mutations for closed events`
  - `4f868a1 fix(events): delete events transactionally`
  - `3783e07 fix(payments): restrict payment confirmation to receivers`
- Закрыты auth/API gaps:
  - `a71b322 fix(auth): add refresh token rotation grace period`
  - `227ee30 feat(payments): add payment deletion endpoint`
  - `ba1a8be feat(receipts): add receipt detail endpoint`
  - `1d9c162 fix(api): configure explicit CORS origins`
- Добавлены profile, storage lifecycle и audit behavior:
  - `ac177f5 feat(users): add current-user profile updates`
  - `fb7820c feat(receipts): add receipt image deletion and presigned URLs`
  - `ee19e9e fix(data): soft-delete records with audit trail`
- Добавлено operational hardening:
  - `2f9602f feat(logging): add structured request logging`
  - `f7ffc4c feat(monitoring): expose metrics and optional error reporting`
  - `9d1ca93 build(deploy): add systemd deployment path`
  - `f070de9 build(lint): add Ruff lint and format checks`
- Добавлены critical authorization, money и storage fixes:
  - `991f607 fix(events): restrict event management to creators`
  - `94f33eb fix(payments): prevent sender impersonation`
  - `d7d44e1 fix(users): limit user listing to visible participants`
  - `ec18396 fix(money): use Decimal for monetary calculations`
  - `9dff159 fix(receipts): keep receipt images private in S3`
- Добавлены backend v2 product flows:
  - `2c68bb0 refactor(money): store monetary values in kopecks`
  - `9687e84 feat(api): add idempotency for financial create endpoints`
  - `f2f58be feat(events): model event memberships with roles`
  - `e0e6658 feat(events): add invite token flow`
  - `02e3874 feat(receipts): require confirmation before balances`
  - `ce7b266 fix(receipts): validate item allocations against memberships`
  - `75f7665 feat(balances): explain simplified event debts`
  - `e41a70a feat(payments): add request and confirmation workflow`
  - `e8a35f6 docs(api): document backend v2 financial flows`
- Завершены backend-feasible product-spec extensions без AI/OCR:
  - `c63560f feat(users): add discovery and payment hints`
  - `d9c9d98 feat(friends): add private friendship flow`
  - `31274a2 feat(events): add nearby invite codes`
  - `05b9348 feat(events): add event settlement policies`
  - `de50b39 feat(receipts): add versioned lifecycle states`
  - `e0cfc70 feat(receipts): store split and fiscal metadata`
  - `c868478 feat(receipts): add allocation sessions`
  - `fb21b1c feat(payments): add request lifecycle actions`
  - `6151e0c feat(disputes): add event dispute tracking`
  - `df48e0f feat(audit): expose event activity feed`
  - `a2e6261 feat(users): add profile financial stats`
  - `a4e8954 feat(reports): add categories and CSV export`
  - `e246716 feat(security): add rate limiting for sensitive endpoints`
  - `b00f682 docs(ai): record receipt agent backlog`

## Запушенные Branches

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

- `make test`: 86 passed, 4 warnings.
- `make lint`: all checks passed.
- Warnings связаны с `fastapi.testclient` deprecation и коротким test-only JWT secret.

## Оставшаяся Frontend Работа

Эти пункты относятся к `/Users/strongf/Developer/SplitApp Yandex/SplitApp` и
намеренно не менялись в backend series:

- Загружать debts в `FriendsView` из backend balances/payments, а не оставлять empty state.
- Реализовать настоящий `settleDebt()` network call через backend payment endpoints.
- Привязать receipt swipe-delete к `DELETE /api/receipts/{id}`.
- Подключить `LocalFriendsStore` к `FriendsViewModel` или удалить, если server является source of truth.
- Улучшить offline indication.
- Удалить dead `.swift` file с dot-only name.
- Использовать CoreData `Payment` mapping или удалить unused persistence code.
- Нормализовать server error presentation вместо raw alerts.
- Обновить frontend list decoders и pagination UI под backend envelope `items` / `limit` / `offset` / `total`.

## Notes

- Backend pagination реализован для `GET /api/events`, `GET /api/users`, `GET /api/events/{id}/receipts` и `GET /api/events/{id}/payments`; frontend list clients еще должны перейти на paginated response envelope.
- Transactional event deletion требует MongoDB topology с transaction support.
- `/api/metrics` защищен `METRICS_ACCESS_TOKEN`; production deployment все равно должен убрать endpoint с публичной user-facing surface через reverse proxy или network policy.
- `GET /api/users` возвращает только current user и users из общих active events, а не всю user table.
- Новые receipt, payment и balance money values используют integer kopecks в API и MongoDB. Legacy decimal-string records читаются совместимо во время rollout.
- Receipt image uploads не используют public object ACLs. Clients должны читать изображения через presigned URL endpoint.
- Event authorization использует `event_memberships` с ролями `creator` и `member`.
- Invite link/QR backend support реализован через token preview, accept и revoke endpoints.
- Новые receipts стартуют как `draft` и влияют на balances только после `POST /api/receipts/{id}/confirm`.
- Balance explanation и payment request flows поддержаны backend'ом; frontend integration остается out of scope для backend branch.
- AI/OCR receipt parsing намеренно не реализован. Future receipt draft agent boundary описан в `docs/wiki/Receipt-Agent-Backlog.md` и заблокирован OCR/model/provider/privacy contracts.
- CSV export реализован для event debts, receipts и payments. PDF export остается future work.

# P0 Safety Flows

Backend реализует P0 как API-first safety layer. Клиенты все еще должны
построить PWA и iOS screens, которые показывают эти состояния пользователю.

## Event Safety Defaults

Новые events используют explicit review по умолчанию:

- `safety_policy = explicit_review`
- `review_window_seconds = 86400`
- `auto_confirm_on_timeout = false`

Auto-confirm отключен намеренно: финансовые изменения должны пройти human review.

## Confirmation Summary Endpoints

Перед необратимыми или чувствительными действиями UI может запросить summary:

- `GET /api/events/{id}/close/confirmation-summary`
- `GET /api/receipts/{id}/confirm/confirmation-summary`
- `GET /api/receipts/{id}/void/confirmation-summary`
- `GET /api/payments/{id}/confirm/confirmation-summary`
- `GET /api/payments/{id}/reject/confirmation-summary`

Каждый response возвращает resource, action, current status, amount when relevant
и warnings. Клиент должен показать explicit confirmation до mutation endpoint.

## Receipt Review Flow

1. `POST /api/events/{id}/receipts` создает draft receipt.
2. `POST /api/receipts/{id}/validate` переводит чек в `pending_confirmation` и
   создает share reviews.
3. Участники принимают или оспаривают свои доли:
   - `POST /api/receipts/{id}/share-reviews/me/accept`
   - `POST /api/receipts/{id}/share-reviews/me/dispute`
4. `POST /api/receipts/{id}/confirm` разрешен только когда все required reviews
   accepted и нет disputes.

Confirmed receipts влияют на balances. Draft, disputed, voided и corrected
receipts не должны менять итоговый debt ledger.

## Invite Decisions

Invite flows поддерживают decline без вступления в событие:

- `POST /api/invites/{token}/decline`

Это нужно, чтобы клиент мог показать пользователю осознанный выбор и не
оставлять ambiguous invite state.

## Payment Safety

Payment request и payment confirmation разделены:

- debtor может создать pending payment через `mark-paid`;
- receiver должен подтвердить payment;
- только confirmed payments влияют на balances;
- confirmed payments нельзя delete, reject или перевести обратно в pending.

## Audit Trail

Security-sensitive actions пишут audit/domain events: receipts, payments,
payment requests, profile updates, deletes и confirmation state changes.

# P0 Safety Flows

Backend реализует P0 как API-first safety layer. Клиенты все еще должны
построить iOS screens, которые показывают эти состояния пользователю.

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

## Settlement Plan Safety

Settlement optimization тоже работает как explicit-review flow:

- `GET /api/events/{id}/settlement-preview` только читает state и доступен даже для
  closed event;
- клиент не присылает свой финансовый граф: backend сам строит preview из
  confirmed receipts/payments и source graph из `GET /api/events/{id}/balances/explain`;
- `POST /api/events/{id}/settlement-plans` разрешен только для open event и только
  если optimization реально уменьшает число переводов;
- при создании plan backend сохраняет canonical snapshot состояния, ставит TTL 24 часа
  (`expires_at`) и вычисляет required approvers из всех source participants, включая
  промежуточных участников с нулевой итоговой net position;
- plan lifecycle использует точные статусы `pending`, `approved`, `rejected`,
  `stale`, `expired`, `executing`, `partially_settled`, `completed`;
- `stale` защищает от гонок: backend сравнивает текущее состояние события с canonical
  snapshot, который был сохранен в `POST /api/events/{id}/settlement-plans`, а не с каким-то
  более ранним read-only preview; если balances/memberships успели измениться после создания
  plan, snapshot помечается как неактуальный;
- `POST /api/settlement-plans/{id}/execute` не создает confirmed payment и не меняет
  balances сам по себе: он только materialize'ит уникальные `payment_requests` с
  provenance-полями `origin=settlement_plan`, `settlement_plan_id`, `settlement_edge_id`;
- дальше безопасность оплаты остается прежней: debtor делает `mark-paid`, receiver делает
  `confirm`, и только confirmed payments влияют на balances и progress settlement plan.

## Audit Trail

Security-sensitive actions пишут audit/domain events: receipts, payments,
payment requests, settlement plans, profile updates, deletes и confirmation state changes.

# Доменные сценарии

## Основной expense flow

1. Пользователь логинится через Yandex в iOS-приложении.
2. iOS отправляет Yandex OAuth token в `POST /api/login`.
3. Backend возвращает app access token и refresh token.
4. Пользователь создает или открывает событие.
5. Creator события добавляет участников.
6. Пользователь создает чек с payer, total amount, items и item shares.
7. Backend валидирует membership, closed-event state и share payload.
8. Backend сохраняет чек.
9. Клиент читает `GET /api/events/{id}/balances`; для audit/optimization UI при необходимости
   дополнительно использует `GET /api/events/{id}/balances/explain` и
   `GET /api/events/{id}/settlement-preview`.
10. Debtor либо создает standalone payment declaration, либо отмечает request как оплаченный
    через `POST /api/payment-requests/{id}/mark-paid`.
11. Receiver подтверждает payment через `POST /api/payments/{id}/confirm`.

## Lifecycle события

| State | Backend behavior |
| --- | --- |
| Open event | Authorized members могут создавать receipts/payments/settlement plans и выполнять settlement execution. |
| Closed event | Financial mutations заблокированы, чтение для members остается доступным. |
| Deleted event | Удаление creator-only и очищает связанные event data через service logic. |

## Lifecycle чека

| Operation | Backend rule |
| --- | --- |
| Create | Caller должен быть event member. Payer и share users должны быть валидны для event. |
| Update | Caller должен быть event member. Closed events отклоняют financial mutation. |
| Delete | Caller должен быть authorized для event. Security-sensitive deletes должны быть soft deletes, если нет документированного исключения. |
| Image upload | Только JPEG, multipart form-data, private object storage. |
| Image read | Использовать presigned URL endpoint для временного доступа. |
| Image replace/delete | Storage operation должна удалять или заменять старый object state. |

## Balance model

`GET /api/events/{id}/balances` возвращает уже globally simplified список долгов:

```json
[
  {
    "event_id": "event-uuid",
    "debitor_id": "user-uuid",
    "creditor_id": "user-uuid",
    "amount_kopecks": 125050
  }
]
```

Интерпретация:

- `debitor_id` должен деньги.
- `creditor_id` должен получить деньги.
- `amount_kopecks` - integer amount in kopecks.

Для объяснения того, откуда взялись эти долги, backend отдает
`GET /api/events/{id}/balances/explain`: там лежит raw pairwise graph с
`contributions` от confirmed receipts и confirmed payments. Optimized edge в
`GET /api/events/{id}/balances` может связывать участников, между которыми не было
прямого receipt/payment edge; это нормальный результат netting, а не фиктивное
«переприсвоение» receipt ownership.

## Settlement optimization flow

1. Member открывает `GET /api/events/{id}/settlement-preview`.
2. Backend read-only пересчитывает preview из raw debt graph:
   - `raw_debts` для audit;
   - `net_positions` для итоговых owes/receives;
   - `recommended_transfers` из server-side algorithm `greedy-net-v1`.
3. Preview доступен и для closed event, потому что сам по себе ничего не записывает.
4. `POST /api/events/{id}/settlement-plans` разрешен только для open event и только если
   preview реально уменьшает число переводов (`recommended_transfer_count < original_transfer_count`).
5. При создании plan backend сохраняет canonical snapshot текущих raw debts, net positions,
   recommended transfers и active memberships, задает TTL 24 часа (`expires_at`) и вычисляет
   required approvers из всех участников исходного debt graph, включая net-zero intermediaries.
6. Required approvers используют `POST /api/settlement-plans/{id}/approve` или
   `POST /api/settlement-plans/{id}/reject`.
7. Lifecycle plan использует точные backend statuses:
   `pending` -> `approved` / `rejected` / `stale` / `expired` -> `executing` ->
   `partially_settled` -> `completed`.
8. `POST /api/settlement-plans/{id}/execute` не двигает деньги и не подтверждает оплаты:
   endpoint только создает уникальные payment requests для edge'ов плана.
9. Дальше каждый debtor делает `POST /api/payment-requests/{id}/mark-paid`, а receiver —
   `POST /api/payments/{id}/confirm`.
10. Только confirmed payments уменьшают balances и продвигают plan к
    `partially_settled` или `completed`.

Клиент не отправляет backend свой settlement graph: backend сам строит plan из состояния
конкретного event и не позволяет использовать edge'ы из другого события.

## Payment confirmation flow

1. Creditor может создать payment request через `POST /api/events/{id}/payment-requests`.
2. Debtor отмечает request как оплаченный через `POST /api/payment-requests/{id}/mark-paid`.
3. Backend создает linked pending payment и пока не меняет balances.
4. Receiver видит payment в списке платежей события.
5. Receiver подтверждает через `POST /api/payments/{id}/confirm`.
6. Backend проверяет, что authenticated actor является receiver.

Это защищает от sender impersonation и от ситуации, когда sender сам подтверждает свой платеж как полученный.

## Правило closed event

Когда `is_closed=true`, backend должен отклонять операции, меняющие финансы события:

- Создание или обновление чека.
- Создание payment.
- Создание settlement plan.
- Execute settlement plan.
- `mark-paid`, confirmation/rejection payment и другие money-changing operations.

Read endpoints должны продолжать работать для event members, включая
`GET /api/events/{id}/balances`, `GET /api/events/{id}/balances/explain`,
`GET /api/events/{id}/settlement-preview`, `GET /api/events/{id}/settlement-plans`
и `GET /api/settlement-plans/{id}`.

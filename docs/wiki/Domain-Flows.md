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
9. iOS читает `GET /api/events/{id}/balances`.
10. Debtor создает payment declaration.
11. Receiver подтверждает payment.

## Lifecycle события

| State | Backend behavior |
| --- | --- |
| Open event | Authorized members могут создавать receipts/payments. |
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

`GET /api/events/{id}/balances` возвращает список долгов:

```json
[
  {
    "event_id": "event-uuid",
    "debitor_id": "user-uuid",
    "creditor_id": "user-uuid",
    "amount": "1250.50"
  }
]
```

Интерпретация:

- `debitor_id` должен деньги.
- `creditor_id` должен получить деньги.
- `amount` - decimal money value.

## Payment confirmation flow

1. Debtor создает payment declaration через `POST /api/events/{id}/payments`.
2. Backend проверяет, что authenticated actor является sender.
3. Receiver видит payment в списке платежей события.
4. Receiver подтверждает через `PATCH /api/payments/{id}`.
5. Backend проверяет, что authenticated actor является receiver.

Это защищает от sender impersonation и от ситуации, когда sender сам подтверждает свой платеж как полученный.

## Правило closed event

Когда `is_closed=true`, backend должен отклонять операции, меняющие финансы события:

- Создание или обновление чека.
- Создание payment.
- Любые будущие money-changing operations.

Read endpoints должны продолжать работать для event members.


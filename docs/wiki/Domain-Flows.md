# Domain Flows

## Main Expense Flow

1. User logs in through Yandex in the iOS app.
2. iOS sends Yandex OAuth token to `POST /api/login`.
3. Backend returns app access and refresh tokens.
4. User creates or opens an event.
5. Event creator adds participants.
6. User creates receipt with payer, total amount, items, and item shares.
7. Backend validates event membership, closed-event state, and share payloads.
8. Backend stores receipt and recalculates balances when requested.
9. iOS reads `GET /api/events/{id}/balances`.
10. Debtor creates payment declaration.
11. Receiver confirms payment.

## Event Lifecycle

| State | Backend behavior |
| --- | --- |
| Open event | Receipts and payments can be created by authorized members. |
| Closed event | Financial mutations are blocked. Existing data can still be read by authorized members. |
| Deleted event | Event delete is creator-only and removes related event data through service logic. |

## Receipt Lifecycle

| Operation | Backend rule |
| --- | --- |
| Create | Caller must be an event member. Payer and share users must be valid for the event. |
| Update | Caller must be an event member. Closed events reject financial mutation. |
| Delete | Caller must be authorized for the event. Security-sensitive deletes should stay soft-delete unless documented otherwise. |
| Image upload | JPEG only, multipart form-data, private object storage. |
| Image read | Use presigned URL endpoint for temporary access. |
| Image replace/delete | Storage operation must explicitly handle old object deletion or replacement behavior. |

## Balance Model

`GET /api/events/{id}/balances` returns a list of debts:

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

Interpretation:

- `debitor_id` owes money.
- `creditor_id` should receive money.
- `amount` is decimal money value.

## Payment Confirmation Flow

1. Debtor creates a payment declaration with `POST /api/events/{id}/payments`.
2. Backend verifies the authenticated actor is the sender.
3. Receiver sees the payment in event payment list.
4. Receiver confirms through `PATCH /api/payments/{id}`.
5. Backend verifies the authenticated actor is the receiver.

This prevents sender impersonation and prevents a sender from confirming their own declaration as received.

## Closed Event Rule

When `is_closed=true`, the backend should reject operations that change event finances:

- Create/update receipt.
- Create payment.
- Other future money-changing operations.

Read endpoints should still work for event members.


# P0 Safety Flows

This backend implements P0 as an API-first safety layer. Clients must still build
the PWA and iOS screens that present these states to users.

## Event Safety Defaults

New events use explicit review by default:

- `safety_policy = explicit_review`
- `review_window_seconds = 86400`
- `auto_confirm_on_timeout = false`

The backend rejects attempts to enable auto-confirm on timeout. A timeout is only
metadata for clients and background reminders; it never turns silence into debt.

## Invites

Invite preview is safe to show before joining an event. Link and nearby-code
invites support explicit decline:

- `POST /api/invites/{token}/decline`
- `POST /api/nearby-invites/{code}/decline`

Decline records an actor decision and does not create event membership. Preview
responses include `actor_decision` when the current user has accepted or
declined.

## Receipt Review Lifecycle

Receipts start as `draft` and do not affect balances. The creator or payer calls
`POST /api/receipts/{id}/validate` to move the receipt to
`pending_confirmation` and create one `ReceiptShareReview` per participant found
in receipt shares.

Required review actions:

- `GET /api/receipts/{id}/share-reviews`
- `POST /api/receipts/{id}/share-reviews/me/accept`
- `POST /api/receipts/{id}/share-reviews/me/dispute`

`POST /api/receipts/{id}/confirm` succeeds only after every required review is
accepted. Disputed, pending, draft, voided, and corrected receipts do not affect
pairwise balances.

## Home Summary

`GET /api/home/summary` returns separate money buckets:

- `confirmed`: net confirmed receipt/payment balances.
- `pending`: pending receipt reviews, payment requests, and standalone pending
  payments.
- `disputed`: disputed receipt reviews and disputed payment requests.

Self-shares are ignored in money buckets, matching the balance ledger behavior.

## Explicit Confirmation Screens

Clients can fetch confirmation summaries before mutating financial state:

- `GET /api/events/{id}/close/confirmation-summary`
- `GET /api/receipts/{id}/confirm/confirmation-summary`
- `GET /api/receipts/{id}/void/confirmation-summary`
- `GET /api/payments/{id}/confirm/confirmation-summary`
- `GET /api/payments/{id}/reject/confirmation-summary`

Frontend follow-up work should render these summaries before calling the final
mutating endpoints.

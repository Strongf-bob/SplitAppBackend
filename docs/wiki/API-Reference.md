# API Reference

The canonical API contract is [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml). This page is a human-readable map of the current backend surface.

## Servers

| Environment | Base URL |
| --- | --- |
| Local development | `http://localhost:8000` |
| Production | `https://splitapp.tech` |

## Authentication

Most endpoints require:

```http
Authorization: Bearer <access_token>
```

Public endpoints:

- `POST /api/login`
- `POST /api/refresh`

## Auth Endpoints

| Method | Path | Purpose | iOS usage |
| --- | --- | --- | --- |
| `POST` | `/api/login` | Exchange Yandex OAuth token for app access and refresh tokens. | `AuthUserEndpoint` |
| `POST` | `/api/refresh` | Rotate refresh token and issue a new access token. | `RefreshTokenEndpoint` |

## Users

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/users` | List users visible to the current user. | Returns current user and users sharing active events with the caller. |
| `PATCH` | `/api/users/me` | Update current user's profile. | Accepts name, email, avatar URL. |

## Events

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events` | Create event. | Creator becomes the event owner. |
| `GET` | `/api/events` | List events visible to caller. | Caller must be creator or participant. |
| `GET` | `/api/events/{id}` | Get event details. | Membership required. |
| `PATCH` | `/api/events/{id}` | Update event name or `is_closed`. | Creator-only management. |
| `DELETE` | `/api/events/{id}` | Delete event. | Creator-only; deletes related receipts and payments through service logic. |
| `POST` | `/api/events/{id}/participants` | Add participants. | Creator-only management. |
| `DELETE` | `/api/events/{id}/participants/{user_id}` | Remove participant. | Creator-only management. |

## Receipts

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events/{id}/receipts` | Create receipt with items and shares. | Event membership required; blocked for closed events. |
| `GET` | `/api/events/{id}/receipts` | List event receipts. | Event membership required. |
| `GET` | `/api/receipts/{id}` | Get receipt details. | Event membership required. |
| `PATCH` | `/api/receipts/{id}` | Update receipt. | Event membership required; blocked for closed events. |
| `DELETE` | `/api/receipts/{id}` | Delete receipt. | Event membership required; soft-delete behavior is handled in services. |
| `POST` | `/api/receipts/{id}/image` | Upload JPEG receipt image. | Multipart field can be `file` or `image`. |
| `DELETE` | `/api/receipts/{id}/image` | Delete receipt image. | Deletes/replaces storage state, not upload-only behavior. |
| `GET` | `/api/receipts/{id}/image/presigned-url` | Get temporary private image URL. | Use this instead of permanent public image URLs. |

## Balances

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/events/{id}/balances` | Calculate event debts. | Returns debtor-creditor edges for the event. |

## Payments

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events/{id}/payments` | Create payment declaration. | Sender must be the authenticated user. |
| `GET` | `/api/events/{id}/payments` | List event payments. | Event membership required. |
| `PATCH` | `/api/payments/{id}` | Confirm or update payment state. | Confirmation is restricted to the receiver. |
| `DELETE` | `/api/payments/{id}` | Delete unconfirmed payment. | Intended for cleanup of mistaken declarations. |

## Health And Operations

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/health/db` | MongoDB health check. | Used for operational checks. |
| `GET` | `/api/metrics` | Prometheus metrics. | Protect by deployment or network policy if public. |

## Error Shape

Standard client-facing errors use:

```json
{
  "detail": "Error message"
}
```

Unexpected server failures should return a generic `500` response and log internal details with request context.


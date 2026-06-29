# iOS Frontend Integration

This page tracks the backend contract used by the iOS app in [Strongf-bob/SplitApp](https://github.com/Strongf-bob/SplitApp). Backend work happens in this repository; iOS code changes belong in the separate frontend repository.

## Current iOS Network Shape

The iOS app uses:

- `APIClient.shared` for network requests.
- Endpoint structs under `SplitApp/Data/Network/Endpoints`.
- Repository layer objects for events, receipts, users, balances, and payments.
- `TokenStore` and Keychain-backed refresh-token storage.
- Core Data for local caching in several data repositories.

Relevant frontend files:

- [`APIClient.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Core/Network/APIClient.swift)
- [`EventEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/EventEndpoints.swift)
- [`ReceiptEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/ReceiptEndpoints.swift)
- [`PaymentEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/PaymentEndpoints.swift)
- [`BalanceEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/BalanceEndpoints.swift)
- [`UserEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/UserEndpoints.swift)

## Endpoint Mapping

| iOS endpoint | Backend endpoint | Status |
| --- | --- | --- |
| `AuthUserEndpoint` | `POST /api/login` | Implemented. |
| `RefreshTokenEndpoint` | `POST /api/refresh` | Implemented. |
| `ListUsersEndpoint` | `GET /api/users` | Implemented, visibility-limited. |
| `CreateEventEndpoint` | `POST /api/events` | Implemented. |
| `ListEventsEndpoint` | `GET /api/events` | Implemented. |
| `GetEventEndpoint` | `GET /api/events/{id}` | Implemented. |
| `UpdateEventEndpoint` | `PATCH /api/events/{id}` | Implemented. |
| `DeleteEventEndpoint` | `DELETE /api/events/{id}` | Implemented. |
| `AddParticipantsEndpoint` | `POST /api/events/{id}/participants` | Implemented. |
| `RemoveParticipantEndpoint` | `DELETE /api/events/{id}/participants/{user_id}` | Implemented. |
| `CreateReceiptEndpoint` | `POST /api/events/{id}/receipts` | Implemented. |
| `ListReceiptsEndpoint` | `GET /api/events/{id}/receipts` | Implemented. |
| `UpdateReceiptEndpoint` | `PATCH /api/receipts/{id}` | Implemented. |
| `DeleteReceiptEndpoint` | `DELETE /api/receipts/{id}` | Implemented. |
| `UploadReceiptImageEndpoint` | `POST /api/receipts/{id}/image` | Implemented. |
| `GetBalancesEndpoint` | `GET /api/events/{id}/balances` | Implemented. |
| `CreatePaymentEndpoint` | `POST /api/events/{id}/payments` | Implemented. |
| `ListPaymentsEndpoint` | `GET /api/events/{id}/payments` | Implemented. |
| `UpdatePaymentEndpoint` | `PATCH /api/payments/{id}` | Implemented. |

## Backend Endpoints Not Yet Fully Reflected In iOS Endpoint Files

| Backend endpoint | Frontend follow-up |
| --- | --- |
| `GET /api/receipts/{id}` | Add a dedicated receipt detail endpoint if screens need a direct detail fetch. |
| `DELETE /api/receipts/{id}/image` | Add image delete flow when users remove or replace receipt photos. |
| `GET /api/receipts/{id}/image/presigned-url` | Use this for private image reads instead of storing long-lived public URLs. |
| `PATCH /api/users/me` | Add profile editing flow if the app allows profile updates. |
| `DELETE /api/payments/{id}` | Add cleanup flow for unconfirmed mistaken payments. |
| `GET /api/metrics` | Do not call from iOS; operations endpoint only. |

## Client Rules

- Always send `Authorization: Bearer <access_token>` except for login and refresh.
- Store refresh token only in secure storage.
- On `401`, refresh once and retry the original request.
- Treat `403` as an authorization or membership failure, not as a networking retry.
- Money values should be decoded as decimal-safe values.
- Receipt image upload must use multipart form-data with JPEG content.
- For receipt images, prefer presigned URLs from the backend.
- Do not trust local cached membership for authorization decisions; backend remains authoritative.

## Known Frontend Follow-Ups

These belong to `/Users/strongf/Developer/SplitApp Yandex/SplitApp`:

- Keep local event and receipt models aligned with backend DTOs.
- Add endpoint support for receipt detail, receipt image deletion, presigned receipt image reads, profile updates, and payment deletion.
- Ensure local development can switch API base URL away from production `https://splitapp.tech`.
- Keep `FriendsView` and settlement UI wired to backend balances and payments.
- Normalize server error presentation for user-facing alerts.
- Add frontend pagination behavior once backend pagination contracts are designed.


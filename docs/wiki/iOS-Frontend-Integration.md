# Интеграция с iOS

Эта страница фиксирует backend-контракт для iOS-приложения в [Strongf-bob/SplitApp](https://github.com/Strongf-bob/SplitApp). Backend-изменения делаются в этом репозитории; iOS-изменения относятся к frontend-репозиторию.

## Текущая сеть в iOS

iOS app использует:

- `APIClient.shared` для network requests.
- Endpoint structs в `SplitApp/Data/Network/Endpoints`.
- Repository layer для events, receipts, users, balances и payments.
- `TokenStore` и Keychain-backed refresh-token storage.
- Core Data для local caching в части repositories.

Связанные frontend-файлы:

- [`APIClient.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Core/Network/APIClient.swift)
- [`EventEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/EventEndpoints.swift)
- [`ReceiptEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/ReceiptEndpoints.swift)
- [`PaymentEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/PaymentEndpoints.swift)
- [`BalanceEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/BalanceEndpoints.swift)
- [`UserEndpoints.swift`](https://github.com/Strongf-bob/SplitApp/blob/main/SplitApp/Data/Network/Endpoints/UserEndpoints.swift)

## Endpoint mapping

| iOS endpoint | Backend endpoint | Status |
| --- | --- | --- |
| `AuthUserEndpoint` | `POST /api/login` | Реализовано. |
| `RefreshTokenEndpoint` | `POST /api/refresh` | Реализовано. |
| `ListUsersEndpoint` | `GET /api/users` | Реализовано, visibility-limited, paginated. |
| `CreateEventEndpoint` | `POST /api/events` | Реализовано. |
| `ListEventsEndpoint` | `GET /api/events` | Реализовано, paginated. |
| `GetEventEndpoint` | `GET /api/events/{id}` | Реализовано. |
| `UpdateEventEndpoint` | `PATCH /api/events/{id}` | Реализовано. |
| `DeleteEventEndpoint` | `DELETE /api/events/{id}` | Реализовано. |
| `AddParticipantsEndpoint` | `POST /api/events/{id}/participants` | Реализовано. |
| `RemoveParticipantEndpoint` | `DELETE /api/events/{id}/participants/{user_id}` | Реализовано. |
| `CreateReceiptEndpoint` | `POST /api/events/{id}/receipts` | Реализовано. |
| `ListReceiptsEndpoint` | `GET /api/events/{id}/receipts` | Реализовано, paginated. |
| `UpdateReceiptEndpoint` | `PATCH /api/receipts/{id}` | Реализовано. |
| `DeleteReceiptEndpoint` | `DELETE /api/receipts/{id}` | Реализовано. |
| `UploadReceiptImageEndpoint` | `POST /api/receipts/{id}/image` | Реализовано. |
| `GetBalancesEndpoint` | `GET /api/events/{id}/balances` | Реализовано. |
| `CreatePaymentEndpoint` | `POST /api/events/{id}/payments` | Реализовано. |
| `ListPaymentsEndpoint` | `GET /api/events/{id}/payments` | Реализовано, paginated. |
| `UpdatePaymentEndpoint` | `PATCH /api/payments/{id}` | Реализовано. |

## Backend endpoints, которые еще стоит явно отразить во frontend

| Backend endpoint | Frontend follow-up |
| --- | --- |
| `GET /api/receipts/{id}` | Добавить receipt detail endpoint, если экрану нужен прямой detail fetch. |
| `DELETE /api/receipts/{id}/image` | Добавить image delete flow при удалении или замене фото чека. |
| `GET /api/receipts/{id}/image/presigned-url` | Использовать для private image reads вместо long-lived public URLs. |
| `PATCH /api/users/me` | Добавить profile edit flow, если приложение позволяет менять профиль. |
| `DELETE /api/payments/{id}` | Добавить cleanup flow для mistaken unconfirmed payments. |
| `GET /api/metrics` | Не вызывать из iOS; это operations endpoint. |

## Правила клиента

- Всегда отправлять `Authorization: Bearer <access_token>`, кроме login и refresh.
- Хранить refresh token только в secure storage.
- На `401` сделать refresh один раз и повторить исходный request.
- `403` трактовать как authorization/membership failure, а не как повод для сетевого retry.
- Money values декодировать как integer kopecks; не выполнять расчеты через floating point.
- Receipt image upload делать multipart form-data с JPEG.
- Для чтения изображений чеков использовать presigned URLs от backend.
- Не доверять local cached membership для authorization; backend остается authoritative.

## Известные frontend follow-ups

Это относится к `/Users/strongf/Developer/SplitApp Yandex/SplitApp`:

- Держать local event/receipt models синхронными с backend DTO.
- Добавить endpoint support для receipt detail, receipt image deletion, presigned receipt image reads, profile updates и payment deletion.
- Сделать переключение API base URL для local development вместо hard-coded production `https://split-app.ru`.
- Держать `FriendsView` и settlement UI привязанными к backend balances/payments.
- Нормализовать server error presentation для user-facing alerts.
- Обновить frontend list decoders под backend pagination envelope: `items`, `limit`, `offset`, `total`.

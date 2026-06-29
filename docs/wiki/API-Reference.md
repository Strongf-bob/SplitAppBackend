# API

Канонический API-контракт находится в [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml). Эта страница - человекочитаемая карта текущего backend API.

## Servers

| Среда | Base URL |
| --- | --- |
| Local development | `http://localhost:8000` |
| Production | `https://splitapp.tech` |

## Authentication

Большинство endpoints требуют:

```http
Authorization: Bearer <access_token>
```

Публичные endpoints:

- `POST /api/login`
- `POST /api/refresh`

## Auth

| Method | Path | Назначение | iOS |
| --- | --- | --- | --- |
| `POST` | `/api/login` | Обмен Yandex OAuth token на app access/refresh tokens. | `AuthUserEndpoint` |
| `POST` | `/api/refresh` | Ротация refresh token и выдача нового access token. | `RefreshTokenEndpoint` |

## Users

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/users` | Список пользователей, видимых текущему actor. | Paginated; возвращает current user и пользователей из общих active events. |
| `PATCH` | `/api/users/me` | Обновить профиль текущего пользователя. | `name`, `email`, `avatar_url`. |

## Events

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events` | Создать событие. | Creator становится owner события. |
| `GET` | `/api/events` | Получить события, видимые caller. | Paginated; caller должен быть creator или participant. |
| `GET` | `/api/events/{id}` | Получить детали события. | Требуется membership. |
| `PATCH` | `/api/events/{id}` | Обновить name или `is_closed`. | Creator-only management. |
| `DELETE` | `/api/events/{id}` | Удалить событие. | Creator-only; service удаляет связанные receipts/payments. |
| `POST` | `/api/events/{id}/participants` | Добавить участников. | Creator-only management. |
| `DELETE` | `/api/events/{id}/participants/{user_id}` | Удалить участника. | Creator-only management. |

## Receipts

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events/{id}/receipts` | Создать чек с items и shares. | Требуется membership; closed event запрещает mutation. |
| `GET` | `/api/events/{id}/receipts` | Список чеков события. | Paginated; требуется membership. |
| `GET` | `/api/receipts/{id}` | Детали чека. | Требуется membership через событие. |
| `PATCH` | `/api/receipts/{id}` | Обновить чек. | Требуется membership; closed event запрещает mutation. |
| `DELETE` | `/api/receipts/{id}` | Удалить чек. | Требуется authorization; delete behavior реализован в service layer. |
| `POST` | `/api/receipts/{id}/image` | Загрузить JPEG изображения чека. | Multipart field: `file` или `image`. |
| `DELETE` | `/api/receipts/{id}/image` | Удалить изображение чека. | Storage state должен быть очищен. |
| `GET` | `/api/receipts/{id}/image/presigned-url` | Получить временный private image URL. | Использовать вместо permanent public URLs. |

## Balances

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/events/{id}/balances` | Рассчитать долги внутри события. | Возвращает debtor-creditor edges. |

## Payments

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events/{id}/payments` | Создать payment declaration. | Sender должен быть authenticated user. |
| `GET` | `/api/events/{id}/payments` | Список платежей события. | Paginated; требуется membership. |
| `PATCH` | `/api/payments/{id}` | Подтвердить или обновить payment state. | Confirmation restricted to receiver. |
| `DELETE` | `/api/payments/{id}` | Удалить unconfirmed payment. | Для cleanup ошибочных declarations. |

## Health и operations

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/health/db` | MongoDB health check. | Operational check. |
| `GET` | `/api/metrics` | Prometheus metrics. | Internal Prometheus scrape endpoint; не публиковать наружу. |

## Error shape

Обычные client-facing ошибки:

```json
{
  "detail": "Error message"
}
```

Unexpected failures должны возвращать generic `500`, а полные детали должны попадать только в server logs.

## Money

API v2 передает денежные значения целыми копейками:

- receipts: `total_amount_kopecks`, `cost_kopecks`;
- payments and balances: `amount_kopecks`.

Backend хранит новые денежные значения в MongoDB как integer kopecks. Старые decimal-string записи читаются совместимо во время rollout, но новые request/response contracts не используют `double`, `Decimal` или рублевые строки.

## Pagination

List endpoints `GET /api/events`, `GET /api/users`, `GET /api/events/{id}/receipts` и `GET /api/events/{id}/payments` принимают query params:

- `limit`: `1..100`, default `50`.
- `offset`: `>= 0`, default `0`.

Ответ:

```json
{
  "items": [],
  "limit": 50,
  "offset": 0,
  "total": 0
}
```

`total` - количество записей, подходящих под authorization/filter rules до применения `limit` и `offset`.

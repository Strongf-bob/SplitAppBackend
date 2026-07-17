# API

Канонический API-контракт находится в [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml). Эта страница - человекочитаемая карта текущего backend API.

## Servers

| Среда | Base URL |
| --- | --- |
| Local development | `http://localhost:8000` |
| Production | `https://split-app.ru` |

## Authentication

Большинство endpoints требуют:

```http
Authorization: Bearer <access_token>
```

Публичные endpoints:

- `GET /api/ping`
- `POST /api/login`
- `POST /api/refresh`

## Auth

| Method | Path | Назначение | iOS |
| --- | --- | --- | --- |
| `POST` | `/api/login` | Обмен Yandex OAuth token на app access/refresh tokens. | `AuthUserEndpoint` |
| `POST` | `/api/refresh` | Ротация refresh token и выдача нового access token. | `RefreshTokenEndpoint` |

## Security

Sensitive endpoints have lightweight per-actor/IP rate limiting and return `429` on excess traffic. Covered scopes include auth login/refresh, user search, and invite preview/accept/create.

Config:

- `RATE_LIMIT_ENABLED`: default `true`.
- `RATE_LIMIT_MAX_REQUESTS`: default `60`.
- `RATE_LIMIT_WINDOW_SECONDS`: default `60`.

## Users

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/users` | Список пользователей, видимых текущему actor. | Paginated; возвращает current user и пользователей из общих active events. |
| `GET` | `/api/users/search` | Поиск зарегистрированных пользователей. | Handle/name требуют `discovery_enabled=true`; телефон сопоставляется только целиком после нормализации. |
| `GET` | `/api/users/me/financial-stats` | Финансовая сводка текущего пользователя. | Open/closed event totals, outstanding owed/receivable kopecks. |
| `POST` | `/api/users/me/contacts/import` | Импорт выбранных контактов текущего пользователя. | Upsert по нормализованному телефону; возвращает matches с локальным `display_name`. |
| `GET` | `/api/users/me/contacts` | Список импортированных контактов текущего пользователя. | Paginated; данные видны только owner user. |
| `PATCH` | `/api/users/me` | Обновить профиль текущего пользователя. | `name`, `email`, `avatar_url`, discovery fields, payment hints. |

Payment phone visibility is conservative: `nobody`, `event_members`, or `friends`. Exact account-phone search does not expose partial matches or enumerate numbers. Contact import is owner-scoped and does not create friend requests automatically.

## Friends

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/friends` | Создать private friend request. | Friendship не равен event membership. |
| `GET` | `/api/friends` | Список friendship records текущего user. | Paginated; optional `status` filter. |
| `POST` | `/api/friends/{id}/accept` | Принять friend request. | Только addressee. |
| `POST` | `/api/friends/{id}/reject` | Отклонить friend request. | Только addressee. |
| `DELETE` | `/api/friends/{id}` | Удалить friendship. | Любая сторона. |
| `POST` | `/api/friends/{id}/block` | Заблокировать friendship. | Любая сторона. |

## Splitik

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/splitik/attachments` | Загрузить image attachment для Splitik message. | Multipart `file`; storage остается private, response содержит только sanitized metadata. |
| `POST` | `/api/splitik/messages` | Отправить сообщение контекстному агенту Сплитику. | Backend validates context, guardrails, capabilities, draft operations, and calls configured LLM provider. Повтор той же отправки передаётся с `Idempotency-Key` и не создаёт второй draft. |
| `GET` | `/api/splitik/sessions/{id}` | Получить историю своей Splitik-сессии. | Только owner сессии. |
| `GET` | `/api/splitik/drafts/{id}` | Получить свой Splitik draft. | Только owner draft. |
| `PATCH` | `/api/splitik/drafts/{id}` | Обновить pending Splitik draft. | Только owner; confirmed money state не меняется. |
| `POST` | `/api/splitik/drafts/{id}/commit` | Подтвердить backend-created draft action. | Поддерживает `create_event` и `create_receipt`; receipt commit создает обычный receipt draft. |

Сплитик работает в режимах `general`, `event`, `receipt`, `member`. Клиент передает entry point и optional `attachment_ids`, но backend заново проверяет actor, event membership, draft owner, attachment owner и видимость target user/receipt. LLM не получает прямого доступа к MongoDB и не может менять состояние без отдельного commit endpoint. Все сообщения пишутся в `splitik_interactions` с sanitized text, `request_id`, status/stage, latency, context summary, guardrail decision and safe error diagnostics.

## Events

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events` | Создать событие. | Creator становится owner события. |
| `GET` | `/api/events` | Получить события, видимые caller. | Paginated; caller должен иметь active event membership. |
| `GET` | `/api/events/{id}` | Получить детали события. | Требуется membership. |
| `PATCH` | `/api/events/{id}` | Обновить name или `is_closed`. | Creator-only management. |
| `GET` | `/api/events/{id}/close/confirmation-summary` | Получить summary перед закрытием события. | Требуется membership; UI должен показать explicit confirmation. |
| `DELETE` | `/api/events/{id}` | Удалить событие. | Creator-only; service удаляет связанные receipts/payments. |
| `POST` | `/api/events/{id}/participants` | Добавить участников. | Creator-only management. |
| `DELETE` | `/api/events/{id}/participants/{user_id}` | Удалить участника. | Creator-only management. |
| `POST` | `/api/events/{id}/invites` | Создать invite token/link для QR или ссылки. | Creator-only; token имеет TTL. |
| `GET` | `/api/invites/{token}/preview` | Посмотреть event preview перед вступлением. | Требует auth, membership не требуется. |
| `POST` | `/api/invites/{token}/accept` | Принять приглашение и стать участником. | Создает или reactivates `member` membership. |
| `POST` | `/api/invites/{token}/decline` | Отклонить invite token. | Записывает user decision без вступления в событие. |
| `DELETE` | `/api/events/{id}/invites/{invite_id}` | Отозвать invite. | Creator-only; revoked token больше не принимается. |

Events return `participants` as membership records with `role` (`creator`, `member`) and `status`. Authorization uses `event_memberships`, not legacy `events.users`.

Event settings include settlement policies: `split_strategy`, `receipt_creation_policy`, `receipt_finalization_policy`, `participants_invite_policy`, `debt_display_mode`, and `settlement_deadline_policy`. Backend enforces receipt creation, receipt confirmation, and participant invite policies.

## Receipts

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events/{id}/receipts` | Создать draft чек с items и shares. | Требуется membership; closed event запрещает mutation; нужен `Idempotency-Key`. |
| `POST` | `/api/events/{id}/receipt-drafts/ai` | Создать AI draft чека из текста через primary/verification/escalation model flow. | Требуется membership; draft требует human review и не влияет на balances. |
| `GET` | `/api/events/{id}/receipts` | Список чеков события. | Paginated; требуется membership. |
| `GET` | `/api/receipt-categories` | Список стандартных категорий чеков. | Для UI metadata; custom category можно хранить на receipt. |
| `GET` | `/api/receipts/{id}` | Детали чека. | Требуется membership через событие. |
| `PATCH` | `/api/receipts/{id}` | Обновить чек. | Financial fields нельзя менять после confirmation; title можно обновить. |
| `POST` | `/api/receipts/{id}/confirm` | Подтвердить draft чек. | Только confirmed receipts влияют на balances. |
| `GET` | `/api/receipts/{id}/confirm/confirmation-summary` | Получить summary перед confirmation. | Для explicit confirmation UI. |
| `POST` | `/api/receipts/{id}/validate` | Перевести чек в review state. | Создает share-review records для участников долей. |
| `GET` | `/api/receipts/{id}/share-reviews` | Получить reviews долей чека. | Paginated; требуется event membership. |
| `POST` | `/api/receipts/{id}/share-reviews/me/accept` | Принять свою долю в чеке. | Только участник, для которого создан review. |
| `POST` | `/api/receipts/{id}/share-reviews/me/dispute` | Оспорить свою долю в чеке. | Требует reason; чек становится disputed. |
| `POST` | `/api/receipts/{id}/void` | Аннулировать confirmed чек. | Voided receipts не влияют на balances. |
| `GET` | `/api/receipts/{id}/void/confirmation-summary` | Получить summary перед void. | Для explicit confirmation UI. |
| `POST` | `/api/receipts/{id}/corrections` | Создать correction draft для confirmed чека. | Original получает `corrected`, новая draft требует confirmation. |
| `POST` | `/api/receipts/{id}/allocation-session` | Запустить collaborative allocation session. | Только draft receipt; creator/payer. |
| `GET` | `/api/allocation-sessions/{id}` | Получить session state и item claims. | Требуется event membership. |
| `POST` | `/api/allocation-sessions/{id}/claims` | Claim receipt item для текущего user. | Session должна быть collecting. |
| `DELETE` | `/api/allocation-sessions/{id}/claims` | Unclaim receipt item. | Удаляет claim текущего user. |
| `POST` | `/api/allocation-sessions/{id}/ready` | Отметить session ready for review. | Creator/payer. |
| `POST` | `/api/allocation-sessions/{id}/finalize` | Пересобрать shares по claims. | Receipt становится `ready_for_review`, но balances меняются только после confirm. |
| `DELETE` | `/api/receipts/{id}` | Удалить чек. | Требуется authorization; delete behavior реализован в service layer. |
| `POST` | `/api/receipts/{id}/image` | Загрузить JPEG изображения чека. | Multipart field: `file` или `image`; response `image_url` является временным presigned URL. |
| `DELETE` | `/api/receipts/{id}/image` | Удалить изображение чека. | Storage state должен быть очищен. |
| `GET` | `/api/receipts/{id}/image/presigned-url` | Получить временный private image URL. | Использовать вместо permanent public URLs. |

## Balances

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/events/{id}/balances` | Рассчитать долги внутри события. | Возвращает deterministic recommended simplification из `greedy-net-v1`, которая сохраняет net positions и строится поверх raw debt graph. |
| `GET` | `/api/events/{id}/balances/explain` | Объяснить рассчитанные долги. | Возвращает raw pairwise obligations с `contributions` от confirmed receipts и confirmed payments для audit/explanation; это исходный граф, а не упрощенный settlement result. |

Упрощение в `GET /api/events/{id}/balances` строится из net positions и source graph из
`GET /api/events/{id}/balances/explain`. Это deterministic recommendation алгоритма
`greedy-net-v1`, а не доказанный глобальный минимум по числу переводов. Оно может соединять
участников, между которыми не было прямого receipt/payment edge, поэтому клиент не должен
трактовать simplified edge как «владение чеком» или как фиктивную историю прямых переводов.

## Settlement optimization

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/events/{id}/settlement-preview` | Посмотреть read-only preview оптимизации переводов. | Доступен member'у и для open, и для closed event; ничего не записывает; возвращает `raw_debts`, `net_positions`, `recommended_transfers` и счетчики сокращения переводов. |
| `POST` | `/api/events/{id}/settlement-plans` | Создать settlement plan по текущему preview. | Только open event; нужен `Idempotency-Key`; backend разрешает создание только когда `transfer_count_reduced=true`, сохраняет canonical snapshot и ставит TTL 24 часа через `expires_at`. |
| `GET` | `/api/events/{id}/settlement-plans` | Список settlement plans события. | Требуется membership; возвращает текущий lifecycle (`pending`, `approved`, `rejected`, `stale`, `expired`, `executing`, `partially_settled`, `completed`). |
| `GET` | `/api/settlement-plans/{id}` | Получить один settlement plan. | Требуется доступ к тому же event; response включает preview, approvals и edge progress. |
| `POST` | `/api/settlement-plans/{id}/approve` | Подтвердить plan snapshot. | Разрешено только user из `required_approver_ids`; status становится `approved` только когда одобрили все required approvers. |
| `POST` | `/api/settlement-plans/{id}/reject` | Отклонить pending plan с причиной. | Разрешено только required approver; причина обязательна и хранится в ответе. |
| `POST` | `/api/settlement-plans/{id}/execute` | Материализовать plan в payment requests. | Только open event; нужен `Idempotency-Key`; endpoint создает только уникальные `payment_requests` на edge'ы и не подтверждает платежи автоматически. |

`required_approver_ids` совпадает с `source_participant_ids` из preview: это все участники
исходного raw debt graph, включая промежуточных участников, у которых итоговая net position
может быть нулевой, но чьи связи исчезают из optimized plan.

Settlement plan edge содержит server-generated `edge_id` и может позже получить
`payment_request_id` и `status`. Клиент не отправляет backend свой финансовый граф и не
может создать cross-event settlement edge: все edge'ы сервер строит сам из текущего состояния
события и проверяет по `event_id`, `settlement_plan_id` и `settlement_edge_id`.

## Payments

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/events/{id}/payments` | Создать payment declaration. | Sender должен быть authenticated user. |
| `GET` | `/api/events/{id}/payments` | Список платежей события. | Paginated; требуется membership. |
| `POST` | `/api/events/{id}/payment-requests` | Создать просьбу оплатить. | Creditor должен быть authenticated user; нужен `Idempotency-Key`. |
| `GET` | `/api/events/{id}/payment-requests` | Список просьб оплатить. | Paginated; требуется membership. |
| `POST` | `/api/payment-requests/{id}/acknowledge` | Debtor отмечает, что увидел просьбу. | Не меняет баланс. |
| `POST` | `/api/payment-requests/{id}/cancel` | Creditor отменяет просьбу. | Можно отменить active/disputed request. |
| `POST` | `/api/payment-requests/{id}/request-extension` | Debtor просит продление. | Не меняет deadline автоматически. |
| `POST` | `/api/payment-requests/{id}/dispute` | Открыть спор по просьбе оплаты. | Ставит status `disputed`. |
| `POST` | `/api/payment-requests/{id}/mark-paid` | Debtor нажимает "я оплатил". | Создает pending payment; нужен `Idempotency-Key`. |
| `POST` | `/api/payments/{id}/confirm` | Receiver подтверждает оплату. | Только confirmed payments уменьшают balances. |
| `GET` | `/api/payments/{id}/confirm/confirmation-summary` | Получить summary перед confirmation. | Для explicit confirmation UI. |
| `POST` | `/api/payments/{id}/reject` | Receiver отклоняет оплату. | Rejected payments не влияют на balances. |
| `GET` | `/api/payments/{id}/reject/confirmation-summary` | Получить summary перед reject. | Для explicit confirmation UI. |
| `PATCH` | `/api/payments/{id}` | Receiver-only update confirmation flag. | Исторически совместимый endpoint; confirmed payment нельзя откатить обратно в pending. |
| `DELETE` | `/api/payments/{id}` | Удалить unconfirmed payment. | Для cleanup ошибочных declarations. |

Payment requests may include `deadline_at`; backend rejects deadlines less than 30 minutes out.

Settlement execution не создает payment confirmations: после `POST /api/settlement-plans/{id}/execute`
каждый должник отдельно проходит `POST /api/payment-requests/{id}/mark-paid`, а получатель отдельно
подтверждает через `POST /api/payments/{id}/confirm`. Только confirmed payments меняют balances.

## Reports

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/events/{id}/export.csv` | CSV export долгов, чеков и платежей события. | Требуется event membership; PDF export пока TODO. |

## Disputes

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/disputes` | Создать спор по receipt/payment/payment_request. | Требуется event membership через resource. |
| `GET` | `/api/events/{id}/disputes` | Список споров события. | Paginated; требуется event membership. |
| `POST` | `/api/disputes/{id}/resolve` | Закрыть спор. | Creator-only MVP resolution. |

## Activity

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/events/{id}/activity` | Event activity/audit feed. | Paginated; виден active event members. |

## Client reports

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/client-reports` | Принять клиентский error/feedback report. | Endpoint доступен до полной авторизации; если Bearer token валиден, backend привязывает `actor_user_id`. Payload санитизируется и сохраняет только allowlist metadata без tokens/raw responses. |

## Health и operations

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/ping` | Lightweight liveness check. | Public endpoint для runtime smoke checks. |
| `GET` | `/api/health/db` | MongoDB health check. | Operational check. |
| `GET` | `/api/metrics` | Prometheus metrics. | Требует `Authorization: Bearer <METRICS_ACCESS_TOKEN>`; не публиковать наружу. |

## Home

| Method | Path | Назначение | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/home/summary` | Сводка главного экрана текущего пользователя. | Events, pending reviews, payment requests и lightweight activity. |

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

Receipt updates support optimistic locking through `expected_version`; stale versions return `409`.
Receipt items can carry `split_mode` metadata while `share_items` remain authoritative. Receipts also store fiscal metadata such as discount, service fee, delivery fee, tip, rounding adjustment, fiscal total, and VAT in kopecks.

## Idempotency

Financial create endpoints require `Idempotency-Key`:

- `POST /api/events/{id}/receipts`;
- `POST /api/events/{id}/payments`;
- `POST /api/events/{id}/payment-requests`;
- `POST /api/payment-requests/{id}/mark-paid`;
- `POST /api/events/{id}/settlement-plans`;
- `POST /api/settlement-plans/{id}/execute`.

Повтор того же actor + endpoint scope + key + payload возвращает сохраненный response. Повтор того же key с другим payload возвращает `409`.

## Pagination

Paginated list endpoints, including events, users, friends, receipts, payments, payment requests, disputes, and activity feeds, accept query params:

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

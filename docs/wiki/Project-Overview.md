# Обзор проекта

## Назначение

SplitAppBackend - серверная часть приложения SplitApp для разделения общих расходов. Backend отвечает за пользователей, авторизацию, события, чеки, расчет долгов, платежи, изображения чеков и API-контракт для iOS-приложения.

Frontend не должен самостоятельно принимать решения по доступу к данным. Источник правды для membership, прав на операции, балансов и платежей - backend.

## Runtime stack

- FastAPI entrypoint: [app/main.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/main.py)
- Совместимый entrypoint: [main.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/main.py)
- MongoDB config/connection: [app/core/db.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/db.py)
- S3-compatible storage для изображений чеков: [app/core/s3.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/s3.py)
- JWT/token helpers: [app/core/tokens.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/tokens.py)
- Monitoring: [app/core/monitoring.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/monitoring.py)

## Слои приложения

| Слой | Файлы | Ответственность |
| --- | --- | --- |
| App wiring | `app/main.py` | Создание FastAPI app, routers, CORS, logging middleware, exception handler, lifecycle setup. |
| Routers | `app/routers/*.py` | HTTP paths, dependencies, response models. |
| Schemas | `app/schemas.py` | Pydantic request/response models. |
| Services | `app/services/*.py` | Бизнес-правила, authorization checks, работа с persistence. |
| Core | `app/core/*.py` | Database, tokens, object storage, monitoring. |
| Tests | `tests/*.py` | Regression coverage для auth, events, money, receipts, payments, config и services. |

## Карта routers

- `app/routers/auth.py` - `/api/login`, `/api/refresh`.
- `app/routers/users.py` - `/api/users`, `/api/users/me`.
- `app/routers/events.py` - события, участники, балансы.
- `app/routers/receipts.py` - чеки и изображения чеков.
- `app/routers/payments.py` - платежи.
- `app/routers/health.py` - health checks и metrics.

## Основные сущности

| Сущность | Что означает |
| --- | --- |
| User | Пользователь, известный backend после авторизации. |
| Event | Пространство общих расходов. Пользователь видит событие, только если он creator или participant. |
| Event membership | Отдельная связь user-event, которая является источником правды для доступа к событию. |
| Receipt | Расход внутри события. Содержит payer, total amount, items и shares. |
| Receipt item | Строка чека с названием, стоимостью и распределением долей. |
| Share item | Доля конкретного пользователя в позиции чека. |
| Balance | Рассчитанный долг от debitor к creditor внутри события. |
| Payment | Заявление, что один пользователь оплатил долг другому пользователю. |

Полная внутренняя схема collections, связей, lifecycle статусов и индексов
описана в [Data model](Data-Model).

## Важные инварианты

- Каждый protected endpoint работает от authenticated actor.
- Client-supplied user IDs не дают прав сами по себе.
- Event membership ограничивает чтение и финансовые операции.
- Event management restricted to creator там, где меняется состав участников или lifecycle события.
- Closed events блокируют financial mutations.
- Receipt image storage приватный; frontend должен получать временные presigned URLs.
- Money calculations используют integer kopecks для новых API/MongoDB значений, не floats.

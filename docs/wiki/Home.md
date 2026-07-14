# Wiki SplitAppBackend

Русскоязычная точка входа в документацию backend-а SplitApp. Выберите маршрут по своей задаче: понять продукт, подключить клиент, запустить и сопровождать сервис или поддержать саму Wiki.

## Продукт и доменная логика

- [Обзор проекта](Project-Overview) — границы ответственности backend-а и состав системы.
- [Доменные сценарии](Domain-Flows) — события, участники, чеки, долги, планы расчётов и платежи.
- [Модель данных](Data-Model) — коллекции MongoDB, состояния и правила source of truth.
- [Сплитик](Splitik-Agent) — контекстный помощник, сессии и подтверждаемые черновики действий.
- [Бэклог AI-разбора чеков](Receipt-Agent-Backlog) — границы текущей реализации и зависимости от внешних провайдеров.

### Карта реализованных способностей

| Способность | HTTP-маршруты | Сервисная логика | Контракт |
| --- | --- | --- | --- |
| События, участники, приглашения, балансы и планы расчётов | [events router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/events.py#L12-L246) | [events](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/events.py#L230-L480), [balances](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/balances.py#L152-L171), [settlements](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/settlements.py#L497-L538) | [OpenAPI: events](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L502-L1649) |
| Чеки, распределение позиций, подтверждение, аннулирование и изображение | [receipts router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/receipts.py#L22-L304) | [receipts](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/receipts.py#L226-L970) | [OpenAPI: receipts](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L2293-L3536) |
| Платежи и платёжные запросы | [payments router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/payments.py#L12-L175) | [payments](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/payments.py#L76-L697) | [OpenAPI: payments](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L3539-L4379) |
| Вход через Яндекс и обновление токенов | [auth router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/auth.py#L13-L32) | [auth](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/auth.py#L142-L218) | [OpenAPI: auth](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L189-L370) |
| Пользователь, друзья и контакты | [users router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/users.py#L10-L73), [friends router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/friends.py#L12-L69) | [users](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/users.py#L202-L261), [contacts](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/contacts.py#L81-L141) | [OpenAPI: users and friends](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L1652-L2290) |
| Сплитик: сообщения, вложения, сессии и черновики | [Splitik router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/splitik.py#L14-L103) | [draft commit](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/splitik_tools.py#L256-L291) | [OpenAPI: Splitik](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L4428-L4738) |

## Интеграция с backend-ом

- [Справочник API](API-Reference) — ресурсы, методы, модели запросов и ответов.
- [Аутентификация и безопасность](Authentication-And-Security) — Bearer-токены, права доступа, CORS и ограничения запросов.
- [Интеграция с iOS](iOS-Frontend-Integration) — правила использования backend-контракта клиентом.

Публичный контракт — [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml); приложение собирает все router-группы в одном FastAPI-приложении с обязательной аутентификацией по умолчанию ([исходный код](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/main.py#L223-L242)).

## Техническая документация

- [Локальный запуск](Local-Setup) — окружение разработчика и запуск API.
- [Операции и деплой](Operations-And-Deployment) — Docker Compose, production-конфигурация, логи и метрики.
- [Тесты и CI](Testing-And-CI) — проверки перед изменением и автоматизация.

Для быстрой диагностики сервис предоставляет маршруты ping, проверки MongoDB и метрик ([router](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/health.py#L9-L28), [OpenAPI](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L6-L89)).

## Онбординг и поддержка Wiki

Новый участник команды: начните с [Обзора проекта](Project-Overview), затем пройдите [Локальный запуск](Local-Setup), [Справочник API](API-Reference) и [Тесты и CI](Testing-And-CI).

Для авторов документации: [Поддержка Wiki](Wiki-Maintenance) описывает хранение исходников в репозитории, синхронизацию и правила обновления. Исходные Markdown-файлы Wiki находятся в [`docs/wiki/`](https://github.com/Strongf-bob/SplitAppBackend/tree/main/docs/wiki) ([подтверждение в инструкции](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/wiki/Wiki-Maintenance.md#L3-L25)).

## Репозитории

- [Backend: Strongf-bob/SplitAppBackend](https://github.com/Strongf-bob/SplitAppBackend)
- [iOS-клиент: Strongf-bob/SplitApp](https://github.com/Strongf-bob/SplitApp)

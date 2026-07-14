---
title: "Вики SplitAppBackend"
description: "Русскоязычная точка входа в продуктовую, интеграционную и техническую документацию SplitApp Backend."
---

# Вики SplitAppBackend

Русскоязычная точка входа в документацию серверной части SplitApp. Выберите маршрут по своей задаче: понять продукт, подключить клиент, запустить и сопровождать сервис или поддержать саму Вики.

## Продукт и доменная логика

- [Обзор продукта](Product-Overview) — ценность, границы и роли продукта.
- [Путь пользователя](User-Journey) — события, участники, чеки, долги, планы расчётов и платежи.
- [Модель данных](Data-Model) — коллекции MongoDB, состояния и правила единого источника истины.
- [Помощник Splitik](Splitik-Assistant) — контекстный помощник и подтверждаемые черновики действий.
- [Жизненный цикл чека](Receipt-Lifecycle) — статусы, распределение позиций и границы AI-помощи.

### Карта реализованных способностей

| Способность | HTTP-маршруты | Сервисная логика | Контракт |
| --- | --- | --- | --- |
| События, участники, приглашения, балансы и планы расчётов | [маршруты событий](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/events.py#L12-L245) | [сервис событий](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/events.py#L230-L480), [сервис балансов](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/balances.py#L152-L171), [сервис расчётов](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/settlements.py#L497-L538) | [OpenAPI: события](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L502-L1649) |
| Чеки, распределение позиций, подтверждение, аннулирование и изображение | [маршруты чеков](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/receipts.py#L22-L304) | [сервис чеков](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/receipts.py#L226-L970) | [OpenAPI: чеки](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L2293-L3536) |
| Платежи и платёжные запросы | [маршруты платежей](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/payments.py#L12-L175) | [сервис платежей](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/payments.py#L76-L697) | [OpenAPI: платежи](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L3539-L4379) |
| Вход через Яндекс и обновление токенов | [маршруты аутентификации](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/auth.py#L13-L31) | [сервис аутентификации](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/auth.py#L142-L218) | [OpenAPI: аутентификация](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L189-L370) |
| Пользователь, друзья и контакты | [маршруты пользователей](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/users.py#L10-L72), [маршруты друзей](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/friends.py#L12-L68) | [сервис пользователей](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/users.py#L202-L260), [сервис контактов](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/contacts.py#L81-L140) | [OpenAPI: пользователи и друзья](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L1652-L2290) |
| Сплитик: сообщения, вложения, сессии и черновики | [маршруты Сплитика](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/splitik.py#L14-L102) | [подтверждение черновика](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/services/splitik_tools.py#L256-L291) | [OpenAPI: Сплитик](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L4428-L4738) |

## Интеграция с серверной частью

- [Руководство по API](API-Guide) — правила вызова, ошибки, пагинация и совместимые изменения контракта.
- [Аутентификация и безопасность](Authentication-And-Security) — Bearer-токены, права доступа, CORS и ограничения запросов.
- [Интеграция SplitApp](SplitApp-Integration) — правила использования контракта серверной части клиентом.

Публичный контракт — [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml); приложение собирает все группы маршрутов в одном FastAPI-приложении с обязательной аутентификацией по умолчанию ([исходный код](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/main.py#L223-L242)).

## Техническая документация

- [Руководство contributor](Contributor-Guide) — окружение разработчика, запуск API и безопасное изменение.
- [Операции и деплой](Operations-And-Deployment) — Docker Compose, рабочая конфигурация, логи и метрики.
- [Тесты и CI](Testing-And-CI) — проверки перед изменением и автоматизация.

Для быстрой диагностики сервис предоставляет маршруты проверки доступности, MongoDB и метрик ([маршруты](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/health.py#L9-L28), [OpenAPI](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml#L6-L89)).

## Начало работы и поддержка Вики

Новый участник команды: начните с [Обзора продукта](Product-Overview), затем пройдите [Руководство contributor](Contributor-Guide), [Руководство по API](API-Guide) и [Тесты и CI](Testing-And-CI).

Для авторов документации: [Поддержка Вики](Wiki-Maintenance) описывает хранение исходников в репозитории, синхронизацию и правила обновления. Исходные Markdown-файлы Вики находятся в [`docs/wiki/`](https://github.com/Strongf-bob/SplitAppBackend/tree/main/docs/wiki) ([подтверждение в инструкции](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/wiki/Wiki-Maintenance.md#L3-L25)).

## Репозитории

- [Серверная часть: Strongf-bob/SplitAppBackend](https://github.com/Strongf-bob/SplitAppBackend)
- [iOS-клиент: Strongf-bob/SplitApp](https://github.com/Strongf-bob/SplitApp)

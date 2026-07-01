# SplitAppBackend Wiki

Это Wiki backend-репозитория SplitApp. Здесь собрана рабочая документация по API, запуску, доменной логике, безопасности, деплою, тестам и связи с iOS-приложением.

## Быстрые ссылки

- [Обзор проекта](Project-Overview) - структура репозитория, ответственность backend и основные зависимости.
- [Локальный запуск](Local-Setup) - как поднять backend на машине разработчика.
- [API](API-Reference) - карта endpoints и ссылка на OpenAPI-контракт.
- [Доменные сценарии](Domain-Flows) - как связаны события, чеки, балансы и платежи.
- [Интеграция с iOS](iOS-Frontend-Integration) - контракт backend для frontend-репозитория SplitApp.
- [Аутентификация и безопасность](Authentication-And-Security) - токены, права доступа, storage и базовые правила безопасности.
- [Операции и деплой](Operations-And-Deployment) - production runtime, env-переменные, systemd, логи и метрики.
- [Тесты и CI](Testing-And-CI) - локальные проверки, GitHub Actions и правила для backend-изменений.
- [Поддержка Wiki](Wiki-Maintenance) - как Wiki синхронизируется из репозитория.
- [Сплитик](Splitik-Agent) - контекстный LLM-агент с backend capabilities и подтверждаемыми draft actions.
- [Receipt Agent Backlog](Receipt-Agent-Backlog) - AI/OCR receipt draft boundary, currently blocked on provider contracts.
- [AI Code Review](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/ai-code-review.md) - настройка OpenCodeReview и правила блокировки PR.

## Репозитории

- Backend: [Strongf-bob/SplitAppBackend](https://github.com/Strongf-bob/SplitAppBackend)
- iOS frontend: [Strongf-bob/SplitApp](https://github.com/Strongf-bob/SplitApp)
- OpenAPI-контракт backend: [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml)
- README backend: [README.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/README.md)
- Базовые правила безопасности: [docs/security-baseline.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/security-baseline.md)
- Отчет по remediation: [docs/remediation-report.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/remediation-report.md)

## Что сейчас покрывает backend

- Обмен Yandex OAuth token на app access/refresh tokens.
- Ротация refresh token.
- Обновление профиля текущего пользователя.
- Список, opt-in поиск пользователей, friendship flow и профильная финансовая статистика.
- Создание, чтение, обновление, закрытие и удаление событий.
- Управление участниками события через memberships и invite links.
- Versioned receipt lifecycle, позиции чека, доли участников, fiscal metadata и allocation sessions.
- Загрузка, удаление и временный доступ к изображениям чеков.
- Расчет долгов, объяснения балансов и CSV export внутри события.
- Payment requests, mark-paid declarations, confirmation/rejection, disputes and activity feed.
- Контекстный агент Сплитик для объяснения событий, расходов, участников и создания подтверждаемых draft actions.
- Lightweight rate limiting for sensitive auth/search/invite flows.
- Явный CORS, структурные request-логи, Prometheus-метрики и optional error reporting.
- Production-деплой через systemd.

## Источник правды

Главный контракт API - `openapi.yaml`. При изменении backend-поведения в одном изменении нужно синхронизировать:

- Python route/service/schema код.
- `openapi.yaml`.
- Tests.
- Wiki source pages в `docs/wiki/`, если изменение влияет на использование API или разработку.

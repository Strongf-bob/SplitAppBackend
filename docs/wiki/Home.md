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
- Список пользователей, видимых текущему пользователю.
- Создание, чтение, обновление, закрытие и удаление событий.
- Управление участниками события.
- CRUD чеков, позиции чека и доли участников.
- Загрузка, удаление и временный доступ к изображениям чеков.
- Расчет долгов и балансов внутри события.
- Создание, просмотр, подтверждение и удаление платежей.
- Явный CORS, структурные request-логи, Prometheus-метрики и optional error reporting.
- Production-деплой через systemd.

## Источник правды

Главный контракт API - `openapi.yaml`. При изменении backend-поведения в одном изменении нужно синхронизировать:

- Python route/service/schema код.
- `openapi.yaml`.
- Tests.
- Wiki source pages в `docs/wiki/`, если изменение влияет на использование API или разработку.


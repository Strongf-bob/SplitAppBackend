# Полная русскоязычная GitHub Wiki SplitAppBackend — план реализации

> **Для agentic-исполнителей:** REQUIRED SUB-SKILL: использовать `executing-plans` для последовательного выполнения и контрольных точек.

**Цель:** Создать новую подробную русскоязычную GitHub Wiki для SplitAppBackend, зеркальную источнику `docs/wiki/`, с бизнес-документацией и явной интеграцией с репозиторием SplitApp.

**Архитектура:** `docs/wiki/` становится единственным Markdown-источником. Страницы группируются вокруг смысла продукта, клиент-серверной границы, реализации и эксплуатации; после локальной проверки этот набор зеркально публикуется в `SplitAppBackend.wiki.git`.

**Технологии:** Markdown GitHub Wiki, Mermaid, git, GitHub repository links, OpenAPI.

## Глобальные ограничения

- Весь объясняющий текст, таблицы и подписи — на русском языке.
- Ссылки на backend-код ведут на `https://github.com/Strongf-bob/SplitAppBackend/blob/main/`; ссылки на iOS — на `https://github.com/Strongf-bob/SplitApp/blob/main/`.
- Внутренние ссылки GitHub Wiki используют имена страниц без `.md`.
- Факты проверяются по коду и `openapi.yaml`; планы и ограничения маркируются явно.
- Не включать секреты, токены, реальные персональные данные или дампы БД.
- Не изменять API, iOS-код, production-конфигурацию или неотносящиеся пользовательские изменения.

---

### Task 1: Инвентаризировать действующее поведение и подготовить словарь ссылок

**Files:**
- Read: `README.md`, `openapi.yaml`, `app/main.py`, `app/schemas.py`, `app/routers/*.py`, `app/services/*.py`, `app/core/*.py`, `compose.yaml`, `Makefile`, `tests/*.py`.
- Modify: `docs/wiki/Home.md`.

- [ ] Сопоставить router, service и OpenAPI paths с продуктовой способностью.
- [ ] Зафиксировать ссылки на точные строки для всех нетривиальных утверждений.
- [ ] Создать новую `Home.md` с выбором маршрута: продукт, интеграция, техническая документация, онбординг и поддержка Wiki.
- [ ] Убедиться, что `Home.md` ссылается на каждую новую верхнеуровневую страницу.

### Task 2: Создать продуктовую и бизнес-документацию

**Files:**
- Create: `docs/wiki/Product-Overview.md`, `docs/wiki/User-Journey.md`, `docs/wiki/Money-And-Settlement.md`, `docs/wiki/Receipt-Lifecycle.md`, `docs/wiki/Splitik-Assistant.md`.
- Read: `app/routers/events.py`, `app/routers/receipts.py`, `app/routers/payments.py`, `app/routers/disputes.py`, `app/routers/splitik.py`, `app/services/balances.py`, `app/services/settlement_algorithm.py`, `app/services/payments.py`, `app/services/receipts.py`, `app/services/splitik.py`, `app/services/splitik_guardrails.py`.

- [ ] Описать роли, ценность и границы продукта простым языком.
- [ ] Документировать путь пользователя и правила доступа, включая Mermaid-схему.
- [ ] Описать суммы в копейках, долги, оптимизацию переводов, заявки на платёж, подтверждение, спор и закрытие события.
- [ ] Описать жизненный цикл чека, изображений, версий, долей и AI-черновиков.
- [ ] Описать Splitik как помощника с черновиками и границей подтверждения, без обещаний неподтверждённых возможностей.
- [ ] В каждой странице добавить таблицы, подтверждающие ссылки и раздел «Связанные страницы».

### Task 3: Документировать связь SplitAppBackend и SplitApp

**Files:**
- Create: `docs/wiki/SplitApp-Integration.md`, `docs/wiki/API-Guide.md`.
- Read: `openapi.yaml`, `app/dependencies.py`, `app/routers/auth.py`, `app/routers/users.py`, `app/routers/events.py`, `app/routers/receipts.py`, `app/routers/payments.py`.

- [ ] Явно разделить ответственность backend и нативного iOS-клиента.
- [ ] Добавить диаграмму запроса iOS → FastAPI → service → MongoDB/S3 и карту ключевых пользовательских сценариев к endpoint-группам.
- [ ] Описать authentication, пагинацию, ошибки, идемпотентность, деньги и порядок совместимого изменения контракта.
- [ ] Добавить рабочие ссылки на `Strongf-bob/SplitApp`, API-клиент и endpoint files только после проверки их существования в GitHub.

### Task 4: Переписать техническую и эксплуатационную документацию

**Files:**
- Create: `docs/wiki/Architecture.md`.
- Modify: `docs/wiki/Data-Model.md`, `docs/wiki/Authentication-And-Security.md`, `docs/wiki/Operations-And-Deployment.md`, `docs/wiki/Testing-And-CI.md`.
- Read: `app/main.py`, `app/core/db.py`, `app/core/s3.py`, `app/core/tokens.py`, `app/core/monitoring.py`, `app/services/access.py`, `app/services/indexes.py`, `compose.yaml`, `Dockerfile`, `Makefile`, `.github/workflows/*`.

- [ ] Описать слои, доверительные границы, хранилища, наблюдаемость и ключевые запросные пути.
- [ ] Обновить модель данных по фактическим коллекциям, ownership, статусам и индексам.
- [ ] Обновить security page по действительной authentication/authorization модели и безопасному хранению.
- [ ] Обновить operation и CI pages по фактическим командам, Compose, метрикам, логам и проверкам.
- [ ] Везде добавить проверяемые ссылки на исходники и двунаправленные связанные страницы.

### Task 5: Создать маршруты онбординга и правила сопровождения

**Files:**
- Create: `docs/wiki/Onboarding.md`, `docs/wiki/Contributor-Guide.md`, `docs/wiki/Staff-Engineer-Guide.md`, `docs/wiki/Executive-Guide.md`, `docs/wiki/Product-Manager-Guide.md`.
- Modify: `docs/wiki/Wiki-Maintenance.md`.
- Read: `README.md`, `Makefile`, `pyproject.toml`, `compose.yaml`, `docs/wiki/*.md`.

- [ ] Создать hub с выбором аудитории.
- [ ] Подготовить глубоко технические маршруты для contributor и staff, с командами, архитектурой, рисками и чтением кода.
- [ ] Подготовить неинженерные executive и product-manager страницы без фрагментов кода: возможности, риски, ограничения, данные и план развития.
- [ ] Описать порядок изменения `docs/wiki/`, проверки ссылок и зеркальной публикации в `SplitAppBackend.wiki.git`.

### Task 6: Удалить устаревшую структуру, проверить и опубликовать

**Files:**
- Delete: `docs/wiki/Project-Overview.md`, `docs/wiki/Domain-Flows.md`, `docs/wiki/Local-Setup.md`, `docs/wiki/API-Reference.md`, `docs/wiki/Splitik-Agent.md`, `docs/wiki/Receipt-Agent-Backlog.md`, `docs/wiki/iOS-Frontend-Integration.md`.
- Modify: все текущие и новые страницы в `docs/wiki/`.

- [ ] Удалить страницы, которые заменены новой архитектурой, только после того как все внутренние ссылки направлены на новые страницы.
- [ ] Проверить Markdown-ссылки, GitHub URL, наличие файлов, frontmatter, русскоязычность заголовков и синтаксис Mermaid.
- [ ] Выполнить `git diff --check` и локальные документационные проверки.
- [ ] Закоммитить только `docs/wiki/` и связанный план/спецификацию основного репозитория Conventional Commit-ом.
- [ ] Зеркально заменить Markdown-файлы в клоне `SplitAppBackend.wiki.git`, выполнить `git diff --check`, создать отдельный wiki commit и push.
- [ ] Проверить `git ls-remote` и главную страницу `https://github.com/Strongf-bob/SplitAppBackend/wiki`.

## Самопроверка плана

- Покрытие спецификации: Tasks 1–5 реализуют все шесть разделов новой архитектуры; Task 6 проверяет и публикует результат.
- Плейсхолдеры: отсутствуют; все создаваемые/изменяемые/удаляемые страницы и команды публикации указаны явно.
- Границы: изменения ограничены документацией и GitHub Wiki; API и iOS не меняются.

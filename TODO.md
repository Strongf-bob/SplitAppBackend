# SplitApp Project Backlog

Дата сверки: 2026-06-29.

Этот файл разделяет исходный список задач на четыре группы:

- что уже сделано в `SplitAppBackend`;
- что осталось сделать в этом backend-репозитории;
- что требует настройки GitHub или production-инфраструктуры;
- что относится к iOS-приложению `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.

## Уже Сделано В Backend

### Документация И Организация

- [x] **AGENTS.md для backend** — правила работы Codex добавлены в репозиторий.
- [x] **Backend wiki в репозитории** — добавлены страницы в `docs/wiki`.
- [x] **README с локальным запуском и server-runbook** — описаны `.env`, MongoDB, `make run-dev`, systemd.
- [x] **Security baseline** — добавлен `docs/security-baseline.md`.
- [x] **Remediation report** — добавлен `docs/remediation-report.md`.
- [x] **Backend TODO** — этот файл ведет backlog по backend scope.

### Исправленные Backend Проблемы

- [x] **Закрытое событие защищено** — backend запрещает финансовые мутации закрытого события.
- [x] **Каскадное удаление события сделано транзакционным** — удаление backend-сущностей выполняется согласованно.
- [x] **Подтверждение платежа ограничено получателем** — платеж не может подтвердить любой участник.
- [x] **Создание платежа защищено от подмены sender_id** — backend не доверяет клиентскому отправителю.
- [x] **Управление событием ограничено создателем** — изменение события и участников не доступно любому участнику.
- [x] **Refresh token rotation получил grace period** — потеря одного ответа не должна навсегда ломать доступ.
- [x] **DELETE `/api/payments/{id}`** — удаление платежей добавлено.
- [x] **GET `/api/receipts/{id}`** — получение одного чека добавлено.
- [x] **CORS настроен явно** — production/local origins задаются конфигурацией.
- [x] **PATCH `/api/users/me`** — управление профилем текущего пользователя добавлено.
- [x] **Receipt image lifecycle** — upload/delete/presigned URL добавлены.
- [x] **Soft delete и audit fields** — чувствительные удаления не являются безусловным hard delete.
- [x] **GET `/api/users` больше не сливает всех пользователей** — список ограничен видимыми пользователями.
- [x] **Денежная логика переведена на копейки** — API и MongoDB используют integer kopecks вместо `float`/`double`/decimal-string для новых денежных значений.
- [x] **S3-чек не публикуется через public-read ACL** — чтение идет через presigned URL.

### Backend Инфраструктура

- [x] **Backend tests** — добавлен pytest regression suite.
- [x] **Backend lint tooling** — добавлен Ruff и targets `make lint` / `make format-check`.
- [x] **Backend CI** — добавлен GitHub Actions workflow для lint/test.
- [x] **Structured logging** — request logs и request/correlation ID добавлены.
- [x] **Backend metrics** — Prometheus `/api/metrics` и optional Sentry через `SENTRY_DSN`.
- [x] **Systemd deployment path** — добавлен `deploy/splitapp-backend.service`.
- [x] **Backend pagination** — list endpoints переведены на `items` / `limit` / `offset` / `total`.
- [x] **OpenAPI sync** — `openapi.yaml` обновлен под текущие backend contracts.

## Осталось Сделать В Backend

### Product/API

- [ ] **Финансовая статистика профиля** — определить contract и добавить `closedBillsAmount` / `openBillsAmount`.
- [x] **Групповые долги и объяснения** — backend возвращает simplified debtor-creditor rows и `/balances/explain` с receipt/payment contributions.
- [ ] **Push-уведомления: backend contract** — события для нового чека, платежа, подтверждения и закрытия события.
- [x] **Инвайт-ссылки в события** — token preview/accept/revoke backend endpoints добавлены для link/QR сценария.
- [ ] **Категории чеков** — модель, API и аналитика расходов по категориям.
- [ ] **Шаблоны повторяющихся чеков** — backend-модель и API для периодических расходов.
- [ ] **AI/OCR receipt agent** — boundary записан в `docs/wiki/Receipt-Agent-Backlog.md`; реализация заблокирована до выбора OCR/model provider contract.
- [ ] **Экспорт отчета** — PDF/CSV "кто кому сколько".
- [ ] **Мультивалютность** — хранение валюты, правила конвертации и API contract.

### Security/Infra

- [ ] **Rate limiting** — ограничение частоты запросов на API.
- [ ] **Docker** — Dockerfile и docker-compose для локальной разработки.
- [ ] **Production monitoring hardening** — закрыть `/api/metrics` сетевой политикой или авторизацией.
- [ ] **MongoDB transaction requirement** — задокументировать/проверить production topology для транзакций.
- [ ] **Secrets audit** — проверить, что `JWT_SECRET`, OAuth, S3 и MongoDB credentials живут только в env/secrets.

## Требует GitHub Или Production Настройки

Эти задачи не закрываются только изменениями файлов в backend-репозитории.

- [ ] **GitHub branch protection** — запрет прямого push в `main`, required PR reviews, required status checks.
- [ ] **GitHub labels** — bug/security/backend/frontend/infra/docs и приоритеты.
- [ ] **Issue templates** — bug report, feature request, security remediation.
- [ ] **PR template** — summary, testing, migration/security notes.
- [ ] **GitHub environments** — production environment с approvals.
- [ ] **Repository secrets** — production SSH host/user/key, env path, Sentry DSN и другие deploy secrets.
- [ ] **CD activation** — workflow есть, но деплой требует secrets и production server setup.
- [ ] **Production server setup** — `/opt/splitapp/backend`, `/etc/splitapp/backend.env`, systemd enable/start.
- [ ] **Grafana/Sentry/alerts** — реальные dashboards, alert rules и error project setup.
- [ ] **Wiki publication check** — workflow синхронизации есть; нужно проверить, что GitHub Wiki включена и action может пушить в `.wiki.git`.
- [ ] **AI-агент для ревью коммитов** — выбрать GitHub app/action и правила запуска на PR.

## Вынесено Во Frontend Репозиторий

Эти пункты относятся к `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.

### Доделать Начатое

- [ ] **Платежный флоу UI** — экран создания платежа, подтверждение получателем, отображение долгов в `FriendsView`.
- [ ] **Закрытие событий UI** — кнопка закрытия события.
- [ ] **Экран участников события** — добавить/удалить людей, видеть кто в событии.
- [ ] **Финансовая статистика в профиле UI** — вывести `closedBillsAmount` / `openBillsAmount` после backend contract.
- [ ] **Просмотр и загрузка фото чека** — привязать `ReceiptImageViewerSheet`, добавить загрузку из галереи.
- [ ] **Swipe-to-delete чеков на главной** — заменить `onDelete = {}` на вызов backend `DELETE /api/receipts/{id}`.
- [ ] **Пагинация в клиентах** — перейти на backend envelope `items` / `limit` / `offset` / `total`.

### Frontend Проблемы Из Исходного Списка

- [ ] **FriendsView debts** — долги сейчас не грузятся с сервера.
- [ ] **settleDebt()** — заменить локальную заглушку реальным API-запросом.
- [ ] **LocalFriendsStore** — подключить к ViewModel или удалить, если backend является source of truth.
- [ ] **Offline UX** — улучшить индикацию офлайна.
- [ ] **Мертвый `.swift` файл** — удалить или восстановить корректное имя/использование.
- [ ] **CoreData Payment mapping** — использовать или удалить.
- [ ] **Server error presentation** — заменить сырые alerts на нормальную обработку ошибок.
- [ ] **Frontend tests** — добавить unit/UI tests.

## Предлагаемый Порядок Работы

1. Закрыть GitHub setup: branch protection, templates, labels, environments, secrets.
2. Довести production deploy: server env, systemd, CD secrets, smoke check после deploy.
3. Добавить backend rate limiting и Docker, потому что это инфраструктурная база.
4. Перейти во frontend-репозиторий и закрыть интеграцию уже готовых backend endpoints: payments, receipt delete/images, pagination.
5. После этого брать новые product features: categories, advanced debt optimization, export, multicurrency.

# SplitApp TODO

## Организация Проекта
- [ ] **Создать wiki для проекта** — описать архитектуру, API, деплой, рабочие процессы и troubleshooting.
- [ ] **Провести полную настройку GitHub** — branch protection, required checks, labels, issue/PR templates, environments, repository secrets.
- [ ] **Деплой на сервер** — настроить production-сервер, systemd/service env, доступы, мониторинг и rollback-процесс.

## Доделать Начатое
- [ ] **Платёжный флоу** — экран создания платежа, подтверждение получателем, отображение долгов в `FriendsView`. Frontend: `/Users/strongf/Developer/SplitApp Yandex/SplitApp`; backend endpoints уже частично готовы.
- [ ] **Закрытие событий** — кнопка закрытия во фронте; backend уже запрещает мутации закрытого события.
- [ ] **Экран участников события** — добавить/удалить людей, видеть кто в событии. Требует frontend-экрана; backend owner-only endpoints уже есть.
- [ ] **Финансовая статистика в профиле** — вывести `closedBillsAmount` / `openBillsAmount`. Нужен backend contract и frontend UI.
- [ ] **Просмотр и загрузка фото чека** — привязать `ReceiptImageViewerSheet`, добавить загрузку из галереи. Frontend; backend upload/delete/presigned URL уже есть.
- [ ] **Swipe-to-delete чеков на главной** — сейчас `onDelete = {}`. Frontend; backend `DELETE /api/receipts/{id}` уже есть.

## Новые Фичи
- [ ] **Групповые долги и взаимозачёты** — оптимизация «кто кому платит» с минимизацией транзакций.
- [ ] **Push-уведомления** — новый чек в событии, новый платёж, подтверждение, закрытие события.
- [ ] **Инвайт-коды в события** — шеринг ссылкой/кодом вместо поиска по UUID.
- [ ] **Категории чеков** — еда/транспорт/жильё и аналитика расходов по категориям.
- [ ] **Шаблоны повторяющихся чеков** — «коммуналка каждый месяц».
- [ ] **AI-ассистент в приложении** — «раскидай чек поровну», «добавь чаевые 10%», автокатегоризация.
- [ ] **Экспорт отчёта** — PDF/CSV кто кому сколько.
- [ ] **Мультивалютность** — сейчас суммы без валюты.

## Инфраструктура
- [x] **Логирование backend** — structured request logs + correlation/request ID.
- [x] **Метрики backend** — Prometheus `/api/metrics`; optional Sentry через `SENTRY_DSN`.
- [ ] **Мониторинг production** — Grafana/alerts/Sentry project setup на сервере и во frontend.
- [x] **Backend tests** — pytest regression suite.
- [ ] **Frontend tests** — UI/unit tests в `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.
- [x] **CI для backend** — GitHub Actions lint + test.
- [ ] **CD для backend** — workflow добавлен, но требует GitHub Secrets и production server setup.
- [ ] **Docker** — контейнеризация бэка, docker-compose для локальной разработки.
- [ ] **Пагинация** — все списковые ручки API.
- [ ] **Rate limiting** — защита API.
- [ ] **AI-агент для ревью коммитов** — авто-проверка PR.

## Что Не В Этом Репозитории
- Все SwiftUI screens, `FriendsView`, `ReceiptImageViewerSheet`, `onDelete = {}`, offline UX, frontend alerts и frontend tests относятся к `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.
- Wiki, branch protection, GitHub environments, secrets и labels настраиваются в GitHub UI/API, не только изменениями файлов в этом backend repository.

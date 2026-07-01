# SplitApp PWA Product Requirements

## Цель

Нужно сделать web/PWA-версию SplitApp, которая живет в этом backend-репозитории,
разворачивается на одном сервере с backend и дает наставникам быстрый способ
открыть, установить и проверить продукт без установки iOS-сборки.

PWA должна ощущаться как тот же SplitApp: события, участники, чеки, долги,
платежи, друзья, приглашения и Splitик. iOS-приложение остается отдельным
frontend-направлением в `/Users/strongf/Developer/SplitApp Yandex/SplitApp`, но
новая web/PWA-версия должна стать полноценным клиентом для текущего backend API.

## Итоговое состояние

- В backend-репозитории есть отдельная PWA-часть, которую можно развивать
  независимо от Python-кода, но деплоить вместе с backend.
- На выбранном домене есть публичная web-точка входа: пользователь открывает
  сайт с телефона или компьютера и может сразу войти или установить PWA.
- PWA работает на мобильных экранах как приложение и на desktop как нормальный
  web-клиент.
- После установки на телефон появляется ярлык SplitApp, который открывает PWA
  в standalone-режиме.
- Все защищенные данные берутся из backend `/api/*`; web-клиент не содержит
  бизнес-правил авторизации и не подменяет server-side проверки.
- Splitик встроен в PWA как рабочий ассистент, а не как декоративный чат.
- Создание событий через Splitик работает через безопасный draft/confirm-flow.
- Добавление чеков через AI проходит через human review и model cross-check, а
  подтвержденный результат не может самовольно менять долги без backend-валидации.

## Обязательные поверхности продукта

### Public install site

Публичный сайт должен открываться до входа в аккаунт и объяснять продукт через
сам интерфейс, без отдельной маркетинговой посадочной страницы как основного
экрана.

Требования:

- Первый экран должен сразу показывать SplitApp как приложение: вход,
  быстрый preview/screenshots или demo-state, кнопку установки и ссылку открыть
  web-версию.
- Должны быть понятные действия:
  - `Войти`;
  - `Открыть SplitApp`;
  - `Установить приложение`, если браузер поддерживает install prompt;
  - fallback-инструкция для iOS Safari, где install prompt не вызывается
    программно.
- Desktop-версия должна выглядеть как рабочий web-интерфейс, а не как mobile-only
  заглушка.
- Mobile-версия должна быть удобна одной рукой: нижняя навигация, крупные зоны
  нажатия, отсутствие горизонтального скролла.
- Страница должна поддерживать будущий домен без захардкоженных абсолютных URL.

### Installed PWA

PWA должна соответствовать installable PWA baseline:

- web app manifest с названием SplitApp, short name, theme color, background
  color, display mode `standalone` или лучше, start URL, scope и иконками.
- Service worker для app shell, статических ресурсов и безопасного offline
  поведения.
- Рабочий install-flow на Android/Chrome и корректная инструкция для iOS Safari.
- Splash/icon assets для мобильных платформ.
- Standalone mode не должен показывать browser-only навигацию.
- PWA должна корректно обновляться: пользователь не должен оставаться навсегда
  на старом bundle после деплоя.

Offline-поведение должно быть консервативным:

- Разрешено кешировать shell, справочные данные и последний безопасный read-only
  snapshot пользователя.
- Нельзя silently отправлять финансовые мутации из offline-очереди без явного
  подтверждения пользователя после восстановления сети.
- При offline-состоянии create/update/delete/pay/confirm действия должны явно
  показывать, что операция не выполнена на сервере.

## Основные пользовательские сценарии

### Authentication

PWA должна использовать существующий backend auth contract:

- Login через `POST /api/login` с Yandex token.
- Refresh через `POST /api/refresh`.
- Все protected API calls отправляют `Authorization: Bearer <access_token>`.
- На `401` клиент делает один refresh и один повтор исходного запроса.
- На `403` клиент показывает ошибку доступа, а не бесконечный retry.

Требования к безопасности клиента:

- Refresh token хранится только в максимально безопасном доступном web-хранилище.
- Access token не должен попадать в URL, analytics, logs, error reports или
  service-worker cache.
- Logout должен очищать local state, tokens, sensitive caches и session-specific
  Splitик state.

### Home

После входа пользователь видит рабочий dashboard:

- список активных событий;
- общую картину долгов: сколько должен пользователь и сколько должны ему;
- быстрые действия: создать событие, добавить чек, открыть Splitик;
- pending items: неподтвержденные платежи, payment requests, спорные моменты,
  незавершенные allocation sessions;
- offline/network status, если сеть нестабильна.

### Events

PWA должна поддерживать текущую модель событий:

- создание события;
- список событий с backend pagination envelope `{items, limit, offset, total}`;
- detail события;
- редактирование имени и policy-полей события, когда backend разрешает;
- закрытие события;
- удаление события только через backend policy;
- отображение участников, ролей, статусов и creator-only ограничений;
- read-only state для закрытых событий.

Client-side UI не должен показывать destructive или forbidden action как
успешную только потому, что пользователь нажал кнопку. Backend response остается
источником истины.

### Participants, friends and invites

PWA должна поддерживать добавление людей в события через безопасные сценарии:

- видимые пользователи из `GET /api/users`;
- поиск пользователей из `GET /api/users/search`;
- друзья из `GET /api/friends`;
- friend request, accept, reject, remove, block;
- invite link flow:
  - создать invite;
  - показать ссылку/QR/копирование;
  - preview invite;
  - accept invite;
  - revoke invite.

PWA не должна делать открытый global user dump. Если пользователь не виден по
backend-правилам, UI должен вести через invite/friend flow.

### Receipts

PWA должна поддерживать ручной receipt flow, который уже есть на backend:

- создать чек в событии;
- payer выбирается только из участников события;
- суммы вводятся и отображаются в рублях, но в API отправляются как kopecks;
- нельзя использовать float для money calculations;
- чек содержит:
  - title;
  - category;
  - total amount;
  - discount;
  - service fee;
  - delivery fee;
  - tip;
  - rounding adjustment;
  - fiscal total;
  - VAT;
  - список позиций;
  - split mode;
  - share items;
- при создании чека обязателен `Idempotency-Key`;
- редактирование должно учитывать `expected_version`, когда экран работает с
  уже загруженной версией;
- подтверждение чека должно быть отдельным действием;
- void/correction должны быть явно отличимы от удаления;
- удаление должно отражать server-side soft-delete/security policy;
- список чеков использует pagination envelope.

### Receipt images

PWA должна поддерживать image flow:

- upload JPEG через multipart form-data field `file` или `image`;
- replace image без оставления старого object state;
- delete image;
- read private image только через `GET /api/receipts/{id}/image/presigned-url`;
- presigned URL нельзя сохранять как долгоживущий permanent image URL;
- UI должен показывать expiration/fallback reload behavior для истекших image URL.

### Allocation sessions

PWA должна поддерживать совместное распределение позиций:

- start allocation session;
- read allocation session state;
- claim item;
- unclaim item;
- mark ready;
- finalize allocation session;
- отображение, кто какие позиции выбрал;
- запрет финализации, если backend возвращает конфликт или нехватку claims.

### Balances

PWA должна показывать долги так же, как backend их считает:

- `GET /api/events/{id}/balances` для итоговых долгов;
- `GET /api/events/{id}/balances/explain` для объяснения вклада чеков и
  платежей;
- `debitor_id` означает, кто должен;
- `creditor_id` означает, кто должен получить;
- amount показывается пользователю в валютном формате, но хранится как kopecks;
- UI должен объяснять, из каких чеков и платежей возник долг.

### Payments and payment requests

PWA должна поддерживать:

- создание payment declaration через `POST /api/events/{id}/payments`;
- обязательный `Idempotency-Key` для создания платежей;
- список платежей события;
- receiver-only confirmation;
- receiver-only rejection;
- update/delete только если backend разрешает;
- payment request flow:
  - create request;
  - list requests;
  - mark paid;
  - acknowledge;
  - cancel;
  - request extension;
  - dispute.

UI должен явно отличать:

- долг по балансу;
- просьбу оплатить;
- заявление "я оплатил";
- подтвержденный платеж;
- отклоненный платеж.

### Disputes and activity

PWA должна поддерживать:

- создание dispute по поддерживаемым ресурсам;
- список disputes события;
- resolve dispute, если backend разрешает;
- activity feed события;
- отображение audit events понятным языком.

### Reports and export

PWA должна поддерживать:

- список receipt categories;
- export CSV по событию;
- понятное состояние загрузки/ошибки при скачивании файла.

### Profile and settings

PWA должна поддерживать:

- просмотр текущего профиля;
- редактирование доступных полей пользователя;
- financial stats;
- public handle;
- discovery enabled;
- payment phone;
- payment phone visibility;
- logout;
- управление local cache/session data.

## Splitик в PWA

Splitик должен быть частью основного продукта:

- доступен с home, event detail, receipt detail и member context;
- может работать как full-screen chat на mobile;
- может работать как side panel/drawer на desktop;
- сохраняет session state через backend session id;
- показывает context chips, которые backend вернул;
- показывает capabilities, но не доверяет им как authorization source;
- показывает draft actions отдельными подтверждаемыми карточками;
- не пишет пользователю "готово/создал/изменил", если backend не вернул
  committed resource.

Поддерживаемые режимы:

- `general`: профиль пользователя, события, друзья;
- `event`: выбранное событие, участники, чеки, балансы, объяснения;
- `receipt`: выбранный чек и его позиции;
- `member`: конкретный участник внутри события.

Обязательный create-event flow:

- пользователь просит Splitик создать событие;
- backend возвращает draft `create_event`;
- PWA показывает draft с названием события;
- пользователь нажимает подтверждение;
- PWA вызывает `POST /api/splitik/drafts/{id}/commit`;
- только после успешного response UI показывает созданное событие.

Требования к write-flows через Splitик:

- Любой AI write-flow должен быть draft-first.
- Draft не влияет на деньги и membership до commit.
- Commit всегда идет через backend endpoint.
- Backend заново проверяет actor, membership, ownership draft и тип действия.
- PWA не должна отправлять скрытые destructive команды от имени пользователя.
- Пользователь должен видеть, что именно будет создано или изменено.

## AI receipt/check flow

Цель: при добавлении чека PWA может использовать Splitик/AI, чтобы помочь
распознать или структурировать чек, но деньги меняются только после проверки
пользователем и backend-валидации.

Требования к пользовательскому flow:

- Пользователь загружает фото чека или вводит текст/позиции.
- PWA показывает, что результат AI является draft, а не подтвержденным чеком.
- Пользователь видит:
  - распознанные позиции;
  - суммы;
  - общий итог;
  - скидки/сервис/доставку/чаевые/округление;
  - уверенность результата;
  - расхождения между моделями;
  - предупреждения по math mismatch.
- Пользователь может вручную исправить каждую позицию и долю.
- Пользователь выбирает участников/share items.
- Только после явного подтверждения создается обычный receipt через backend.
- После создания receipt требуется отдельный confirm-flow, если backend policy
  этого требует.

Требования к model cross-check:

- Primary model для Splitик/receipt understanding: `MiMo V2 5 Pro`.
- Verification model: `Qwen 3 7 Max`.
- Escalation model при расхождении: `Kimi K2 5`.
- Точные provider model IDs должны быть runtime-configurable и проверены перед
  реализацией, потому что названия в продуктовых требованиях могут отличаться
  от API identifiers провайдера.
- Для чека primary и verification model независимо возвращают структурированный
  draft.
- Если результаты совпадают по критичным полям, draft можно пометить как
  AI-approved, но все равно показать пользователю на проверку.
- Критичные поля:
  - итоговая сумма;
  - список позиций;
  - цена каждой позиции;
  - налоги/скидки/сервис/доставка/чаевые/округление;
  - payer;
  - событие;
  - валюта/kopecks conversion;
  - участники/share assumptions, если модель их предложила.
- Если primary и verification расходятся, запрос уходит в escalation model.
- Escalation model должна выбрать лучший вариант или вернуть merged draft с
  явным списком сомнений.
- При любом расхождении UI показывает пользователю, что именно спорно.
- Даже при совпадении моделей backend обязан валидировать payload как обычный
  create receipt request.

Требования к приватности AI:

- Секреты OpenCode Go/API не попадают в PWA bundle.
- PWA никогда не вызывает model provider напрямую.
- Все model calls идут только через backend.
- В prompts нельзя отправлять refresh/access tokens, private keys, production
  credentials или лишние персональные данные.
- Receipt images/OCR text/model outputs должны иметь понятную retention policy.
- Логи model calls не должны содержать полные персональные данные или платежные
  реквизиты.

## OpenCode Go / model configuration

AI-интеграция должна быть backend-owned.

Требования:

- Provider base URL, API key, model names, timeout, retries и feature flags
  задаются через runtime env.
- Никакие ключи не коммитятся в репозиторий.
- Для PWA доступна только backend API abstraction, не provider credentials.
- Должен быть выключатель AI features на уровне runtime config.
- Если AI provider недоступен, базовые ручные функции PWA продолжают работать.
- Ошибки AI provider показываются пользователю как безопасные generic messages,
  а внутренние детали логируются на backend с request context.

## Security requirements

PWA не должна снижать текущую backend security baseline.

Обязательные правила:

- Client validation является UX, не security boundary.
- Backend остается источником прав для actor, event membership, ownership,
  payment sender/receiver и draft owner.
- Client-supplied user IDs никогда не считаются доказательством прав.
- Все money-changing requests используют server validation.
- Idempotency key обязателен для create receipt, create payment, create payment
  request и любых будущих AI commit operations.
- CORS должен быть явным: production origins + local dev origins.
- Для будущих доменов нельзя оставлять wildcard origins.
- Service worker не должен кешировать authenticated API responses так, чтобы
  другой пользователь на том же устройстве мог их увидеть.
- XSS защита критична: AI/user-generated text, receipt item names, event names
  и notes должны отображаться как text, а не как raw HTML.
- CSRF модель должна быть явно выбрана с учетом token storage. Если используется
  cookie-based auth, нужны SameSite/Secure/CSRF protections.
- PWA должна корректно очищать sensitive data при logout, token expiry и смене
  пользователя.
- Error UI не должен раскрывать stack traces, provider responses, tokens или
  database details.
- Upload flow должен ограничивать типы файлов, размер, duplicate submits и
  failed uploads.
- Delete/replacement storage flows должны иметь подтверждение пользователя и
  server-side cleanup.

## UX and quality requirements

PWA должна быть похожа на готовое приложение, а не на технический dashboard.

Требования:

- Интерфейс на русском по умолчанию.
- Все основные операции имеют loading, empty, error и success states.
- Формы не теряют введенные данные при validation error.
- Деньги форматируются единообразно.
- Даты/время используют timezone пользователя, по умолчанию `Europe/Moscow`.
- Mobile navigation: нижние вкладки или эквивалентный app-like pattern.
- Desktop navigation: sidebar/topbar, удобная работа с широким экраном.
- Все touch targets достаточно крупные для телефона.
- Компоненты должны работать в light/dark системной теме или иметь явно
  выбранную аккуратную тему.
- Основные экраны не должны полагаться на hover-only взаимодействия.
- Accessibility baseline:
  - keyboard navigation;
  - visible focus;
  - labels для inputs;
  - alt text для meaningful images;
  - contrast suitable for mobile use.

## API contract requirements for PWA

PWA должна использовать текущие backend endpoints:

- Auth: `POST /api/login`, `POST /api/refresh`.
- Users/profile: `GET /api/users`, `GET /api/users/search`,
  `GET /api/users/me/financial-stats`, `POST /api/users/me/contacts/import`,
  `GET /api/users/me/contacts`, `PATCH /api/users/me`.
- Friends: `POST /api/friends`, `GET /api/friends`,
  `POST /api/friends/{id}/accept`, `POST /api/friends/{id}/reject`,
  `DELETE /api/friends/{id}`, `POST /api/friends/{id}/block`.
- Events: `POST /api/events`, `GET /api/events`, `GET /api/events/{id}`,
  `PATCH /api/events/{id}`, `DELETE /api/events/{id}`.
- Participants/invites: `POST /api/events/{id}/participants`,
  `DELETE /api/events/{id}/participants/{user_id}`,
  `POST /api/events/{id}/invites`, `GET /api/invites/{token}/preview`,
  `POST /api/invites/{token}/accept`,
  `DELETE /api/events/{id}/invites/{invite_id}`.
- Receipts: `POST /api/events/{id}/receipts`,
  `GET /api/events/{id}/receipts`, `GET /api/receipts/{id}`,
  `PATCH /api/receipts/{id}`, `POST /api/receipts/{id}/confirm`,
  `POST /api/receipts/{id}/void`, `POST /api/receipts/{id}/corrections`,
  `DELETE /api/receipts/{id}`.
- Receipt images: `POST /api/receipts/{id}/image`,
  `DELETE /api/receipts/{id}/image`,
  `GET /api/receipts/{id}/image/presigned-url`.
- Allocation sessions: `POST /api/receipts/{id}/allocation-session`,
  `GET /api/allocation-sessions/{id}`,
  `POST /api/allocation-sessions/{id}/claims`,
  `DELETE /api/allocation-sessions/{id}/claims`,
  `POST /api/allocation-sessions/{id}/ready`,
  `POST /api/allocation-sessions/{id}/finalize`.
- Balances: `GET /api/events/{id}/balances`,
  `GET /api/events/{id}/balances/explain`.
- Payments: `POST /api/events/{id}/payments`,
  `GET /api/events/{id}/payments`,
  `POST /api/events/{id}/payment-requests`,
  `GET /api/events/{id}/payment-requests`,
  `POST /api/payment-requests/{id}/mark-paid`,
  `POST /api/payment-requests/{id}/acknowledge`,
  `POST /api/payment-requests/{id}/cancel`,
  `POST /api/payment-requests/{id}/request-extension`,
  `POST /api/payment-requests/{id}/dispute`,
  `POST /api/payments/{id}/confirm`,
  `POST /api/payments/{id}/reject`, `PATCH /api/payments/{id}`,
  `DELETE /api/payments/{id}`.
- Disputes/activity: `POST /api/disputes`, `GET /api/events/{id}/disputes`,
  `POST /api/disputes/{id}/resolve`, `GET /api/events/{id}/activity`.
- Reports: `GET /api/receipt-categories`, `GET /api/events/{id}/export.csv`.
- Splitик: `POST /api/splitik/messages`,
  `GET /api/splitik/sessions/{id}`,
  `POST /api/splitik/drafts/{id}/commit`.
- AI receipt drafts: `POST /api/events/{id}/receipt-drafts/ai` for backend-owned
  primary/verification/escalation model cross-check. The response is a
  human-review draft payload and never changes balances by itself.
- Contact import: PWA can submit only contacts explicitly selected by the user.
  Backend matches those phone numbers privately for the current account, never
  bulk-reads a device address book, and never auto-creates friend requests.
- Current PWA stop point: show the AI receipt draft as an interactive review
  card with editable fields, model disagreement status, and a user confirmation
  button. Confirmation in this step marks the draft as reviewed in the PWA only;
  creating the real backend receipt is a later step.

Если implementation требует нового endpoint, он должен быть оформлен как
backend change: code, tests, `openapi.yaml` и docs обновляются вместе.

## Hosting and domain requirements

Точный домен еще выбирается, но продукт должен поддерживать такую схему:

- публичный web/PWA домен, например `web.<domain>` или основной `<domain>`;
- API на том же домене под `/api/*` или на явном API subdomain;
- CORS configured only for approved production and local development origins;
- install/start URL не должен ломаться при смене домена;
- deep links для invite flow должны открывать PWA и вести в нужный
  экран после login;
- backend health/metrics не должны быть публичным пользовательским UI.

## Acceptance criteria

PWA считается готовой для первой демонстрации, когда:

- Ее можно открыть на desktop browser и mobile browser.
- Ее можно установить как PWA на поддерживаемом mobile browser.
- После входа пользователь может создать событие, добавить участников, создать
  чек, увидеть баланс и создать/подтвердить платеж.
- Invite link работает end-to-end.
- Receipt image upload/read/delete работают через private storage flow.
- Splitик отвечает в `general` и `event` modes.
- Splitик может создать draft события и commit создает событие только после
  подтверждения пользователя.
- AI receipt draft показывает cross-check result и не меняет деньги без ручного
  подтверждения.
- Logout очищает sensitive local state.
- Refresh-token flow работает.
- Direct URL refresh на любом PWA route не ломает приложение.
- `make test` backend проходит после любых backend changes.
- PWA build/lint/test команды задокументированы.
- `openapi.yaml`, docs и requirements остаются синхронными с фактическим API.

## Out of scope for first implementation

- Изменения iOS-приложения в `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.
- Покупка/выбор домена.
- Публикация в App Store или Play Store.
- Банковские интеграции и реальные платежные переводы.
- Полностью автоматическое создание чеков без human review.
- Автоматическое списание/перераспределение долгов по решению модели.
- Публичный global search всех пользователей.
- Админ-панель для просмотра пользовательских данных.

## Handoff notes for implementation agent

- Current implementation starts with a vanilla PWA in `web/`, served by FastAPI
  from `/` and `/app`. It intentionally has no npm build step yet, so it can be
  deployed with the backend immediately and replaced by a richer frontend stack
  later if needed.
- Не начинать с переписывания backend API: сначала использовать существующий
  контракт.
- Если frontend требует нового backend behavior, добавить отдельный backend
  change с тестами и обновлением `openapi.yaml`.
- Не выносить AI keys или OpenCode Go credentials в web bundle.
- Не делать provider calls из браузера.
- Не доверять AI output: все write payloads проходят обычную server validation.
- Не коммитить `.env`, secrets, production credentials, user data или database
  dumps.
- Перед release проверить CORS, service-worker cache policy, token storage,
  XSS-safe rendering и logout cleanup.

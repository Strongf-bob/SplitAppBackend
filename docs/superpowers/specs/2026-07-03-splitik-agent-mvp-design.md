# Splitik Agent MVP Design

## Цель

Сделать Сплитика базовым безопасным AI-агентом SplitApp, а не просто чатиком.
Пользователь должен открыть Сплитика, написать сообщение или загрузить фото
чека, получить уточняющие вопросы, создать draft события или чека, менять этот
draft через чат и получать объяснение своих трат и долгов.

Backend остается источником истины. LLM не получает прямой доступ к MongoDB и
не вызывает произвольные API. Она предлагает намерение, вопросы и структуру
draft, а backend policy layer проверяет доступ, применяет разрешенные операции
и пишет логи.

## Не цель MVP

- Автономный агент с произвольным набором tools.
- Автоматическое изменение денег без явного draft/confirm flow.
- Общий помощник для домашки, программирования или любых задач вне SplitApp.
- Раскрытие частных трат друзей вне общего события и расчетов пользователя.
- Полный frontend/iOS redesign. Backend contract и PWA proof path допустимы,
  но iOS adoption остается отдельной задачей для frontend repo.

## Пользовательские сценарии MVP

### Создание события из текста

Пользователь пишет: "Вчера были в кафе с Ильей и Машей, я платил".

Сплитик должен определить, что это новое событие или новый расход. Если данных
не хватает, он задает уточняющие вопросы: название, участники, дата, сумма,
деление. После достаточного ответа backend создает `create_event` draft.

### Создание чека из текста или фото

Пользователь пишет текст чека или загружает фото. Backend сохраняет attachment
приватно и передает модели только разрешенный input для распознавания. Сплитик
извлекает позиции, суммы и участников, затем спрашивает недостающие детали:
кто что ел, делим ли поровну, кто платил, к какому событию относится чек.

Результат сохраняется как `create_receipt` draft. Балансы и реальные receipts
не меняются до явного подтверждения.

### Редактирование draft через чат

Пользователь пишет: "Убери кофе у Маши", "Добавь чай Илье", "Поменяй сумму на
3200", "Переименуй событие". Backend должен применить это как новую версию
draft, а не как прямое изменение confirmed данных.

### Объяснение личных трат

Пользователь спрашивает: "Сколько я должен?", "Кто мне должен?", "Почему я
должен Илье 500?", "Что у меня по событию Дача?", "Сколько я потратил за все
время?".

Сплитик должен объяснять только данные, доступные текущему пользователю:
личные балансы, собственные платежи, общие события, где пользователь является
участником, и расчетные причины долга.

## Архитектура

### Основной принцип

LLM формулирует намерение, structured draft proposal и текст ответа. Backend
исполняет только разрешенные операции через policy layer:

1. Router принимает сообщение, attachments и session id.
2. Splitik service загружает session, actor и bounded context.
3. Guardrail classifier определяет, относится ли запрос к SplitApp и не
   нарушает ли privacy/safety rules.
4. LLM получает system prompt, bounded context и history summary.
5. LLM возвращает structured response: `assistant_message`, `intent`,
   `questions`, `draft_operation`, `explanation_request` или `refusal`.
6. Backend валидирует structured response через Pydantic schemas.
7. AgentTools применяет только разрешенные операции.
8. Interaction log записывает request, response, guardrail decision, model ids,
   tool calls, draft ids, latency и errors.

### AgentTools

В MVP нужны backend-owned tools:

- `read_user_summary`
- `read_event_summary`
- `read_receipt_context`
- `read_user_balance_summary`
- `create_event_draft`
- `create_receipt_draft`
- `update_draft`
- `commit_draft`

Каждая tool-функция сама проверяет actor, membership, draft owner, статус
события и допустимость операции. LLM не может подставить чужой user id и
получить чужие данные, потому что backend пересобирает scope из actor.

### Draft model

Текущий `splitik_drafts` нужно расширить до универсальной draft-сущности:

- `id`
- `owner_user_id`
- `session_id`
- `type`: `create_event`, `create_receipt`
- `status`: `pending`, `committed`, `cancelled`
- `payload`
- `version`
- `source`: `text`, `image`, `mixed`
- `attachment_ids`
- `questions`
- `model_metadata`
- `created_at`
- `updated_at`
- `committed_at`
- `committed_resource_id`

Редактирование через чат создает новую версию draft или обновляет draft с
инкрементом `version`. Confirm endpoint применяет payload через существующие
domain services.

### Attachments

Для фото нужен backend-controlled attachment flow:

- upload как часть Splitik message или отдельный pre-upload endpoint;
- storage private, без публичных permanent URLs;
- attachment metadata хранится отдельно;
- LLM получает либо OCR/vision text result, либо временно доступный provider
  input без раскрытия storage credentials;
- логи содержат metadata, но не секретные storage URLs.

Для MVP допустим один backend endpoint:
`POST /api/splitik/messages` с multipart-полями `payload` и `attachments`.
Если это усложнит контракт, допускается промежуточный endpoint
`POST /api/splitik/attachments`, который возвращает `attachment_id`.

### Expense explanations

Объяснения должны строиться из существующих balance services:

- event balances;
- balance explanations;
- receipts and payments where actor is a member;
- user-scoped aggregate summary.

LLM получает уже рассчитанные backend facts и превращает их в понятный ответ.
Она не пересчитывает деньги самостоятельно как источник истины.

## Guardrails

MVP guardrails применяются до и после LLM:

- запрос вне SplitApp получает отказ;
- домашка, код, учебные решения и general assistant задачи получают отказ;
- secrets, payment credentials, tokens и private keys не запрашиваются;
- данные чужого пользователя вне общего события не раскрываются;
- данные общего события можно объяснять только active members;
- любые write-действия только draft-first;
- confirmed money state нельзя менять через обычный chat response;
- LLM tool call с чужим user id игнорируется или блокируется;
- unexpected model output не исполняется и возвращает безопасную ошибку.

Guardrail decision должен попадать в interaction log.

## Логирование и аналитика

Добавить коллекцию `splitik_interactions`.

Минимальные поля:

- `id`
- `request_id`
- `session_id`
- `actor_user_id`
- `message_id`
- `input_type`: `text`, `image`, `mixed`
- `sanitized_user_message`
- `attachment_metadata`
- `intent`
- `context_scope`
- `model_ids`
- `assistant_message`
- `structured_response`
- `guardrail_decision`
- `tool_calls`
- `draft_ids`
- `latency_ms`
- `error`
- `created_at`

Логи нужны для анализа качества, расследования regressions и построения набора
постоянных safety tests. Секреты, токены, raw presigned URLs и платежные
credentials в лог не попадают.

## API contract

Основной endpoint:

- `POST /api/splitik/messages`

Response должен поддерживать:

- `session_id`
- `message_id`
- `assistant_message`
- `mode`
- `intent`
- `questions`
- `context_chips`
- `capabilities`
- `drafts`
- `suggested_actions`
- `guardrail_decision`

Дополнительные endpoint MVP:

- `GET /api/splitik/sessions/{id}`
- `GET /api/splitik/drafts/{id}`
- `PATCH /api/splitik/drafts/{id}`
- `POST /api/splitik/drafts/{id}/commit`
- optional `POST /api/splitik/attachments`

OpenAPI, docs and tests must be updated in the same change set.

## Verification

The MVP is complete only when repository tests prove these invariants:

- Splitik creates event draft from text and does not commit it automatically.
- Splitik creates receipt draft from text and does not change balances.
- Splitik creates receipt draft from image/OCR provider result.
- Splitik asks questions when payer, participants, event or split details are
  missing.
- Splitik updates an existing draft through chat commands.
- Draft commit is allowed only for the owner.
- Actor cannot read or edit another actor's Splitik session or draft.
- Actor cannot get event context for an event where they are not a member.
- Splitik refuses homework/general-assistant prompts.
- Splitik refuses requests for another user's private spending outside shared
  event context.
- LLM output that proposes a forbidden operation is blocked by backend policy.
- Every Splitik message writes a `splitik_interactions` record.
- Logs do not contain auth tokens, private storage URLs or payment credentials.
- Runtime LLM model configuration is validated when configured.
- `openapi.yaml`, wiki docs and tests match runtime behavior.

## Implementation phases

### Phase 1: Contract and policy foundation

Define structured Splitik schemas, guardrail decisions, interaction logs,
AgentTools interfaces and universal draft shape. Wire model validation into
startup when LLM config is present.

### Phase 2: Text draft workflows

Implement create/update event draft and create/update receipt draft from text.
Keep commit explicit and owner-scoped.

### Phase 3: Image receipt workflow

Add attachment handling and image-to-receipt-draft flow. Reuse existing private
storage behavior where possible.

### Phase 4: Expense explanations

Add user-scoped and event-scoped explanation tools backed by existing balance
services.

### Phase 5: Safety and regression suite

Add permanent guardrail tests, logging tests, OpenAPI sync checks and docs.

## Acceptance result

After MVP, a user can use Сплитик as a real SplitApp assistant: write or upload
a receipt photo, answer clarifying questions, get a draft, edit the draft via
chat, confirm it explicitly, and ask for personal spending explanations. Backend
policy prevents privacy leaks, unrelated homework/general-assistant use and
unconfirmed money changes, with logs and tests proving those boundaries.

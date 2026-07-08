# Сплитик Agent

Сплитик - контекстный LLM-агент SplitApp. Он отвечает на вопросы о событиях,
расходах, участниках и долгах, но не управляет базой напрямую.

## Runtime config

Сплитик использует OpenAI-compatible chat completions adapter:

- `SPLITIK_LLM_BASE_URL`
- `SPLITIK_LLM_API_KEY`
- `SPLITIK_PRIMARY_MODEL` - primary model for Splitik replies and receipt understanding.
- `SPLITIK_INTENT_MODEL` - optional small model for the intent-router request before planner;
  recommended `deepseek-v4-flash`. Falls back to `SPLITIK_PRIMARY_MODEL`.
- `SPLITIK_VERIFICATION_MODEL` - independent verification model for receipt understanding cross-checks.
- `SPLITIK_ESCALATION_MODEL` - escalation model used when primary and verification results disagree.
- `SPLITIK_LLM_TIMEOUT_SECONDS`
- `SPLITIK_MESSAGE_HOURLY_LIMIT` - default `10` Splitik messages per user per hour.
- `SPLITIK_MESSAGE_DAILY_LIMIT` - default `30` Splitik messages per user per day.
- `SPLITIK_MESSAGE_CONCURRENT_LIMIT` - default `1` active Splitik message per user.
- `SPLITIK_ATTACHMENTS_PER_MESSAGE` - default `3` attachment ids per Splitik message.
- `SPLITIK_ATTACHMENT_DAILY_LIMIT` - default `10` uploaded Splitik attachments per user per day.
- `SPLITIK_MAX_DRAFTS_PER_REQUEST` - default `3` newly created drafts from one planner response.
- `SPLITIK_PENDING_DRAFT_LIMIT` - default `10` pending Splitik drafts per user.
- `EVENT_CREATE_DAILY_LIMIT` - default `5` created events per user per day.
- `RECEIPT_CREATE_DAILY_LIMIT` - default `20` created receipts per user per day.

`SPLITIK_LLM_MODEL` remains a legacy fallback for the primary model only. New
runtime config must use the role-specific variables above so model IDs can be
changed without code changes or rebuilds.

When LLM runtime config is present, backend startup validates all configured
role models against the provider's OpenAI-compatible `/models` endpoint. If a
configured model is unavailable or provider credentials are rejected, startup
fails before serving requests.

Значения секретов должны жить только в runtime `.env` на машине разработчика или
сервере. Не добавлять ключи в `.env.example`, GitHub secrets для CI, docs,
OpenAPI или тестовые fixtures.

## Modes

- `general` - профиль текущего пользователя, его события и accepted friends.
- `event` - конкретное событие, участники, receipts, balances и explanations.
- `receipt` - конкретный расход/чек внутри события.
- `member` - конкретный участник внутри общего события.

Frontend может передать `entry_point`, но backend заново проверяет actor и
доступ к событию, чеку или участнику. Клиентские capabilities не считаются
источником истины.

## Capabilities

Capabilities вычисляются на backend:

- read capabilities: summaries, receipt details, member context, balance explanations.
- draft capabilities: create event, add receipt.
- commit v1: create event and create receipt.
- forbidden capabilities: impersonation, event deletion, direct existing money-state edits,
  marking someone else's payment as paid.

## Draft and commit flow

Сплитик может создать draft action, но draft не меняет деньги и не создает
события или чеки сам по себе. Изменение состояния выполняется только через
`POST /api/splitik/drafts/{id}/commit`, где backend проверяет owner draft,
status и поддерживаемый тип действия.

MVP поддерживает:

- `create_event` draft из текста в `general` mode;
- `create_receipt` draft из текста в `event` mode;
- `create_receipt` draft из image attachment;
- receipt drafts возвращают уточняющие `questions` для payer, participants и
  split details, если данных недостаточно для уверенного подтверждения;
- follow-up answer в той же session может закрыть эти questions и обновить
  metadata активного draft без commit;
- update pending draft через `PATCH /api/splitik/drafts/{id}` или follow-up
  chat command в той же session;
- explicit commit для `create_event` и `create_receipt`.

Confirmed money state не меняется от обычного chat response. Receipt draft
commit создает обычный backend receipt со status `draft`; дальнейшая
confirmation/review логика остается в receipt domain services.

## Attachments

Image attachments хранятся приватно. API и interaction logs возвращают только
metadata (`id`, filename, content type, size), но не bucket/key, private storage
URL или presigned URL. Vision/OCR provider получает sanitized attachment
metadata и event context, после чего backend валидирует результат как
`CreateReceiptRequest`.

Клиент загружает фото через `POST /api/splitik/attachments`, затем передает
полученный `attachment_id` в `POST /api/splitik/messages`.

## Guardrails and logs

Перед вызовом LLM backend применяет deterministic guardrails:

- per-user limits for Splitik messages, concurrent Splitik calls, attachments,
  drafts per request, pending drafts, event creation, and receipt creation;
- out-of-scope homework/general assistant prompts получают refusal;
- requests for passwords, tokens, API keys or payment credentials are refused;
- private friend-spending questions outside shared context are refused;
- foreign sessions, drafts, events, receipts and members return owner/membership
  scoped errors.

После LLM backend дополнительно проверяет assistant response. Если модель
утверждает, что напрямую удалила событие, изменила баланс/долг или подтвердила
чек без committed resource от backend, ответ заменяется безопасным текстом:
"Я не изменил данные напрямую...". Response получает `intent: "guardrail"` и
`guardrail_decision.reason: "unsafe_model_state_change_claim"`.

Этот же post-response слой блокирует private-spending leakage: если модель
начинает рассказывать, на что другой пользователь тратит деньги вне общего
события, backend заменяет ответ privacy refusal и пишет
`guardrail_decision.reason: "unsafe_model_private_spending_claim"`.

Every Splitik message writes `splitik_interactions` for later quality analysis.
The record includes actor, session, message id, `request_id`, sanitized message,
intent, status, processing stage, latency, guardrail decision, context summary,
tool calls, draft ids and model metadata. If a request fails before a normal
assistant response is produced, backend still writes an `intent: "error"` record
with the failed stage, HTTP status when available, error type, safe error message
and traceback hash. Logs redact accidental tokens and must not include auth
tokens, payment credentials, private storage keys or private URLs. Raw LLM
prompts and full backend context are not persisted; `context_summary` stores
counts, entry point identifiers and available tools instead.

## Spending explanations

General spending questions such as "кто мне должен" or "сколько я должен" use
backend-computed balance facts. LLM receives `user_balance_summary` and formats
the answer; it is not the source of financial calculations.

## Runtime chain

Splitik message processing is backend-controlled:

1. `app/routers/splitik.py` receives `POST /api/splitik/messages`, resolves the
   authenticated actor, and forwards `X-Request-ID`.
2. `app/services/splitik.py` checks per-user hourly, daily, attachment-count
   and concurrency limits before expensive context building or LLM calls.
3. `app/services/splitik.py` creates or loads the Splitik session owned by that
   actor.
4. User-message guardrails run before the model. Homework, secrets, and
   private-spending requests can be refused before any LLM call.
5. Backend builds bounded context: actor-visible events, entry point, recent
   session messages, event-scoped active draft, and sanitized attachment
   metadata.
6. `app/services/splitik_llm.py::generate_splitik_intent_candidate` asks the
   LLM for a tiny JSON route: `explain`, `chat`, or `mutation`. This step does
   not create drafts and cannot write to the database. If the user only asks to
   explain something, Splitik skips the planner JSON and goes straight to the
   chat/explanation flow.
7. For `mutation` requests only, `app/services/splitik_llm.py::generate_splitik_plan_candidate` asks the LLM
   for a strict JSON plan. The model can only propose allowlisted actions such
   as `create_event_draft`, `create_receipt_draft`, `update_receipt_draft`, or
   `ask_clarifying_question`.
8. `app/services/splitik.py` caps planner output by draft count and pending
   draft count before any new draft write.
9. `app/services/splitik_guardrails.py::evaluate_planner_action` rejects
   unsupported action types, raw database/tool operations, Mongo-style
   operators, deletes, payments, and direct money-state changes.
10. `app/services/splitik_tools.py` validates allowed planner actions with
   existing domain schemas and access checks, then writes only pending
   `splitik_drafts`.
11. If no safe draft action is produced, Splitik falls back to chat/explanation
   behavior or returns clarifying questions.
12. Assistant text is checked by post-LLM guardrails, then the message and
   diagnostics are stored in `splitik_sessions` and `splitik_interactions`.
13. Real event or receipt documents are created only later through
    `POST /api/splitik/drafts/{id}/commit`.

## Model context and backend tools

Сплитик не отдает модели всю историю пользователя и не дает ей прямой доступ к
MongoDB. Перед каждым LLM-вызовом backend собирает bounded context:

- scope по `mode`: `general`, `event`, `receipt` или `member`;
- `splitik` metadata: mode, locale, timezone;
- `available_tools`: allowlist backend tools, допустимых в текущем mode;
- `tool_results`: результаты уже исполненных серверных reads;
- `conversation_state`: состояние только текущей `session_id` и текущего
  event scope, если он есть;
- `drafts`, если текущий запрос создал или обновил draft;
- `user_balance_summary`, если запрос похож на вопрос о тратах/долгах.
- `attachments`: sanitized metadata по всем `attachment_ids`, без bucket/key,
  private URL или raw content.

MVP tools:

- `splitik.get_active_draft` - последний pending draft текущего пользователя в
  текущей `session_id` и текущем `event_id`, если запрос пришел из события;
- `splitik.get_recent_session_messages` - короткая история сообщений только
  этой Splitik session;
- `splitik.get_event_history` - последние receipts конкретного события после
  membership check;
- `splitik.get_user_spending_summary` - личная сводка долгов и ожидаемых
  поступлений текущего пользователя.

Если клиент передает старую `session_id`, backend может добавить в
`conversation_state.active_draft` текущий pending draft и последние сообщения
этой сессии. Для event mode active draft дополнительно фильтруется по
`event_id`, поэтому фраза "поменяй сумму" в другом событии не меняет старый
чек из предыдущего события. Если `session_id` не передан, создается новая
сессия, старый draft автоматически не подмешивается.

System prompt runtime:

```text
Ты Сплитик, ассистент SplitApp. Отвечай на языке пользователя.
Используй только контекст и инструменты, которые передал backend.
Не утверждай, что изменил данные, если backend не вернул подтвержденный ресурс.
Для любых изменений объясняй шаг draft/подтверждения: сначала создается или
редактируется черновик, а реальные деньги меняются только после явного commit.
Не проси секреты, платежные данные, пароли, токены или приватные данные вне
контекста SplitApp. Не раскрывай личные траты другого пользователя вне общего
события и разрешенного backend-контекста.
```

## Examples

### Create event draft

Client request:

```json
{
  "mode": "general",
  "message": "Создай событие: Ужин в Duo",
  "locale": "ru-RU",
  "timezone": "Europe/Moscow"
}
```

Backend creates a pending draft before any committed event exists:

```json
{
  "type": "create_event",
  "status": "pending",
  "payload": {
    "name": "Ужин в Duo"
  },
  "version": 1,
  "source": "text"
}
```

The planner LLM receives only backend-approved context and returns structured
JSON:

```json
{
  "model": "qwen3.7-plus",
  "messages": [
    {
      "role": "system",
      "content": "Ты planner Splitik. Верни только JSON-план..."
    },
    {
      "role": "user",
      "content": "Сообщение пользователя:\nСоздай событие: Ужин в Duo\n\nРазрешенный backend context JSON:\n{mode, entry_point, recent_messages, active_draft, attachments, allowed_actions}"
    }
  ],
  "temperature": 0.1,
  "response_format": {
    "type": "json_object"
  }
}
```

The model returns a plan:

```json
{
  "intent": "create_drafts",
  "assistant_message": "Подготовил черновик события **Ужин в Duo**.",
  "actions": [
    {
      "type": "create_event_draft",
      "payload": {
        "name": "Ужин в Duo"
      }
    }
  ]
}
```

Backend response:

```json
{
  "intent": "draft",
  "assistant_message": "Подготовил черновик события **Ужин в Duo**.",
  "guardrail_decision": {
    "allowed": true,
    "reason": "allowed"
  },
  "drafts": [
    {
      "type": "create_event",
      "status": "pending",
      "payload": {
        "name": "Ужин в Duo"
      }
    }
  ]
}
```

The event is created only after `POST /api/splitik/drafts/{id}/commit`.

### Create receipt draft from text

Client request in event mode:

```json
{
  "mode": "event",
  "message": "Добавь чек: кофе 1200 рублей",
  "entry_point": {
    "type": "event",
    "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  }
}
```

Backend validates event membership and creates a receipt draft:

```json
{
  "type": "create_receipt",
  "status": "pending",
  "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "source": "text",
  "version": 1,
  "payload": {
    "payer_id": "current-user-id",
    "title": "Черновик чека",
    "total_amount_kopecks": 120000,
    "items": [
      {
        "name": "Позиция из сообщения",
        "cost_kopecks": 120000,
        "split_mode": "custom",
        "share_items": [
          {
            "user_id": "participant-id",
            "share_value": "0.5"
          }
        ]
      }
    ]
  },
  "questions": [
    {
      "id": "payer",
      "text": "Кто платил за этот чек?",
      "required": true
    },
    {
      "id": "participants",
      "text": "Кто участвовал в этом чеке?",
      "required": true
    },
    {
      "id": "split_details",
      "text": "Кто что ел или как делим сумму?",
      "required": true
    }
  ]
}
```

No `receipts` document is created until explicit commit. Receipt draft commit
creates a normal receipt with status `draft`; it still does not become a
confirmed money source until the receipt confirmation flow runs.

### Update draft through chat

Follow-up request in the same session:

```json
{
  "session_id": "same-session-id",
  "mode": "event",
  "message": "Поменяй сумму на 1500 рублей",
  "entry_point": {
    "type": "event",
    "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  }
}
```

Backend finds the latest pending `create_receipt` draft in that session and
updates it:

```json
{
  "version": 2,
  "payload": {
    "total_amount_kopecks": 150000,
    "items": [
      {
        "cost_kopecks": 150000
      }
    ]
  }
}
```

The LLM context for that follow-up includes session-local state:

```json
{
  "available_tools": [
    "splitik.get_active_draft",
    "splitik.get_recent_session_messages",
    "splitik.get_event_history"
  ],
  "tool_results": {
    "splitik.get_active_draft": {
      "id": "draft-id",
      "type": "create_receipt",
      "status": "pending",
      "version": 2
    },
    "splitik.get_recent_session_messages": [
      {
        "user_message": "Добавь чек: кофе 1200 рублей",
        "assistant_message": "Сплитик: готово."
      }
    ]
  },
  "conversation_state": {
    "session_id": "same-session-id",
    "mode": "event",
    "active_draft": {
      "id": "draft-id",
      "type": "create_receipt"
    },
    "recent_messages": [
      {
        "user_message": "Добавь чек: кофе 1200 рублей"
      }
    ]
  }
}
```

If the same text is sent without `session_id`, backend creates a new Splitik
session and `conversation_state.active_draft` is absent. The old pending draft
is still available through its draft API, but it is not treated as the active
chat target.

Follow-up answers to draft questions use the same session-local active draft.
For example:

```json
{
  "session_id": "same-session-id",
  "mode": "event",
  "message": "Я платил, были все участники, делим поровну",
  "entry_point": {
    "type": "event",
    "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  }
}
```

Backend updates the same pending draft, removes answered questions, increments
the version and records which questions were answered:

```json
{
  "intent": "draft",
  "questions": [],
  "drafts": [
    {
      "id": "draft-id",
      "version": 2,
      "questions": [],
      "model_metadata": {
        "answered_question_ids": ["payer", "participants", "split_details"]
      }
    }
  ]
}
```

### Create receipt draft from image

First upload an image:

```http
POST /api/splitik/attachments
Content-Type: multipart/form-data
```

Backend stores the object privately and returns only sanitized metadata:

```json
{
  "id": "attachment-id",
  "filename": "receipt.jpg",
  "content_type": "image/jpeg",
  "size_bytes": 12345,
  "created_at": "2026-07-03T12:00:00Z"
}
```

Then send the attachment to Splitik:

```json
{
  "mode": "event",
  "message": "Создай черновик чека по фото",
  "entry_point": {
    "type": "event",
    "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  },
  "attachment_ids": ["attachment-id"]
}
```

The image model receives sanitized attachment metadata, not bucket/key or a
private storage URL:

```json
{
  "model": "qwen3.7-plus",
  "messages": [
    {
      "role": "system",
      "content": "Ты создаешь черновики чеков SplitApp по metadata фото чека и OCR/vision input. Верни только JSON в форме черновика чека."
    },
    {
      "role": "user",
      "content": "Источник чека пользователя:\nMetadata фото чека:\n{id, filename, content_type, size_bytes, created_at}\n\nРазрешенный backend context JSON:\n{event_id, attachment_ids, human_review_required: true}\n\nВерни только JSON."
    }
  ],
  "temperature": 0.1,
  "response_format": {
    "type": "json_object"
  }
}
```

Expected model response:

```json
{
  "payload": {
    "payer_id": "user-id",
    "title": "Кофе",
    "category": "Кафе",
    "total_amount_kopecks": 1000,
    "items": [
      {
        "name": "Капучино",
        "cost_kopecks": 1000,
        "split_mode": "custom",
        "share_items": [
          {
            "user_id": "user-a",
            "share_value": 0.5
          },
          {
            "user_id": "user-b",
            "share_value": 0.5
          }
        ]
      }
    ]
  },
  "warnings": []
}
```

Backend validates this as `CreateReceiptRequest` and stores a `create_receipt`
draft with `source: "image"`.

### Explain user spending

Client request:

```json
{
  "mode": "general",
  "message": "Кто мне должен деньги?"
}
```

Backend computes money facts and passes them to the LLM:

```json
{
  "user_balance_summary": {
    "outstanding_owed_kopecks": 0,
    "outstanding_receivable_kopecks": 5000,
    "events": [
      {
        "event": {
          "name": "Trip"
        },
        "balances": [
          {
            "debitor_id": "user-b",
            "creditor_id": "user-a",
            "amount_kopecks": 5000
          }
        ]
      }
    ]
  }
}
```

The LLM formats the explanation, but backend remains the source of financial
truth.

### Guardrail refusal

Homework/general assistant request:

```json
{
  "mode": "general",
  "message": "Реши домашку по алгебре"
}
```

Backend refuses before the LLM call:

```json
{
  "intent": "refusal",
  "assistant_message": "Я могу помогать только со SplitApp: событиями, чеками, долгами и личными тратами.",
  "guardrail_decision": {
    "allowed": false,
    "reason": "out_of_scope_homework"
  },
  "drafts": []
}
```

Private friend-spending requests outside shared context are also refused:

```json
{
  "allowed": false,
  "reason": "private_friend_spending"
}
```

Interaction log example:

```json
{
  "actor_user_id": "current-user-id",
  "session_id": "session-id",
  "message_id": "message-id",
  "intent": "draft",
  "sanitized_user_message": "Сколько я должен? token=[REDACTED] Authorization: Bearer [REDACTED]",
  "guardrail_decision": {
    "allowed": true,
    "reason": "allowed"
  },
  "draft_ids": ["draft-id"],
  "created_at": "2026-07-03T12:00:00Z"
}
```

## Demo friends

Для локального заполнения друзей есть скрипт:

```bash
python tools/seed_demo_friends.py --user-name "Илья Карсаков" --confirm-local
```

Для серверного запуска нужен явный флаг:

```bash
python tools/seed_demo_friends.py --user-name "Илья Карсаков" --confirm-server
```

Скрипт идемпотентен: demo users находятся по `public_handle`, friendship records
по `pair_key`.

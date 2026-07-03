# Сплитик Agent

Сплитик - контекстный LLM-агент SplitApp. Он отвечает на вопросы о событиях,
расходах, участниках и долгах, но не управляет базой напрямую.

## Runtime config

Сплитик использует OpenAI-compatible chat completions adapter:

- `SPLITIK_LLM_BASE_URL`
- `SPLITIK_LLM_API_KEY`
- `SPLITIK_PRIMARY_MODEL` - primary model for Splitik replies and receipt understanding.
- `SPLITIK_VERIFICATION_MODEL` - independent verification model for receipt understanding cross-checks.
- `SPLITIK_ESCALATION_MODEL` - escalation model used when primary and verification results disagree.
- `SPLITIK_LLM_TIMEOUT_SECONDS`

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

- out-of-scope homework/general assistant prompts получают refusal;
- requests for passwords, tokens, API keys or payment credentials are refused;
- private friend-spending questions outside shared context are refused;
- foreign sessions, drafts, events, receipts and members return owner/membership
  scoped errors.

Every Splitik message writes `splitik_interactions` with actor, session,
message id, sanitized message, intent, guardrail decision, draft ids and model
metadata. Logs redact accidental tokens and must not include auth tokens,
payment credentials, private storage keys or private URLs.

## Spending explanations

General spending questions such as "кто мне должен" or "сколько я должен" use
backend-computed balance facts. LLM receives `user_balance_summary` and formats
the answer; it is not the source of financial calculations.

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

The LLM receives only backend-approved context:

```json
{
  "model": "qwen3.7-plus",
  "messages": [
    {
      "role": "system",
      "content": "You are Splitik, a SplitApp assistant..."
    },
    {
      "role": "user",
      "content": "User message:\nСоздай событие: Ужин в Duo\n\nAllowed backend context JSON:\n{current_user, events, friendships, splitik, drafts}"
    }
  ],
  "temperature": 0.2
}
```

The model returns assistant text, for example:

```text
Сплитик: готово.
```

Backend response:

```json
{
  "intent": "draft",
  "assistant_message": "Сплитик: готово.",
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
  }
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
      "content": "You create SplitApp receipt drafts from receipt image metadata and OCR/vision input. Return only JSON in the receipt draft shape."
    },
    {
      "role": "user",
      "content": "Receipt image attachment metadata:\n{id, filename, content_type, size_bytes, created_at}\n\nAllowed backend context JSON:\n{event_id, attachment_ids, human_review_required: true}\n\nReturn only JSON."
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

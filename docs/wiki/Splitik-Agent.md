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

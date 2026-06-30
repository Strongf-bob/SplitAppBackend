# Сплитик Agent

Сплитик - контекстный LLM-агент SplitApp. Он отвечает на вопросы о событиях,
расходах, участниках и долгах, но не управляет базой напрямую.

## Runtime config

Сплитик использует OpenAI-compatible chat completions adapter:

- `SPLITIK_LLM_BASE_URL`
- `SPLITIK_LLM_API_KEY`
- `SPLITIK_LLM_MODEL`
- `SPLITIK_LLM_TIMEOUT_SECONDS`

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
- commit v1: create event.
- forbidden capabilities: impersonation, event deletion, direct existing money-state edits,
  marking someone else's payment as paid.

## Draft and commit flow

Сплитик может создать draft action, но draft не меняет деньги и не создает
события сам по себе. Изменение состояния выполняется только через
`POST /api/splitik/drafts/{id}/commit`, где backend проверяет owner draft и
поддерживаемый тип действия.

V1 поддерживает commit только для `create_event`. Остальные write flows должны
оставаться draft-only до отдельного backend policy layer и regression tests.

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

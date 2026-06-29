# Тесты и CI

## Локальные команды

Tests:

```bash
make test
```

Lint:

```bash
make lint
```

Format check:

```bash
make format-check
```

## Текущий CI

Backend CI workflow:

- Запускается на pull requests.
- Запускается на pushes в `main`.
- Запускается на pushes в `strongf/**` branches.
- Устанавливает Python dependencies.
- Запускает Ruff.
- Запускает pytest.
- Deploy делает только на push в `main`.

Workflow source:

- [.github/workflows/ci.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/ci.yml)

## Regression testing expectations

Добавлять или обновлять tests при изменении:

- Authentication behavior.
- Authorization checks.
- Event membership rules.
- Receipt money logic.
- Payment sender/receiver permissions.
- Closed-event behavior.
- Storage deletion/replacement behavior.
- CORS, logging или monitoring behavior.

## Backend change checklist

Для behavior changes:

1. Обновить service или route code.
2. Обновить Pydantic schemas, если payload изменился.
3. Обновить `openapi.yaml`.
4. Добавить или обновить tests.
5. Обновить Wiki source в `docs/wiki/`, если изменилось developer-facing поведение.
6. Запустить `make test`.
7. Запустить `make lint`, если lint tooling доступен.

## Review focus

При review проверять:

- Контролирует ли authenticated actor операцию?
- Есть ли membership/creator authorization в service layer?
- Валидируются ли write payloads на сервере?
- Не раскрывают ли ошибки sensitive internal state?
- Совпадает ли OpenAPI contract с кодом?
- Задокументированы ли frontend follow-ups, если iOS behavior должен измениться?


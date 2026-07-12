# Аутентификация и безопасность

## Authentication model

Backend использует Yandex OAuth как внешний identity provider:

1. iOS получает Yandex token.
2. iOS отправляет его в `POST /api/login`.
3. Backend валидирует Yandex token и создает или находит backend user.

При первом успешном входе backend сохраняет полученные профильные поля и копирует аватар в object storage. Повторный OAuth-вход по-прежнему валидирует credential, но возвращает сохранённый профиль без повторного импорта данных Яндекса. Аватар хранится как `avatar_key` и загружается клиентом через публичный `GET /avatars/{user_id}`.
4. Backend возвращает app access token и refresh token.
5. Protected API calls используют `Authorization: Bearer <access_token>`.
6. `POST /api/refresh` ротирует refresh token и возвращает новый access token.

## Authorization baseline

Backend services должны проверять authenticated actor рядом с защищаемой операцией.

Правила:

- Никогда не доверять client-supplied user IDs без проверки authenticated actor.
- Event reads требуют creator или participant membership.
- Event management creator-only там, где операция меняет membership или lifecycle события.
- Payment creation требует, чтобы authenticated actor был sender.
- Payment confirmation требует, чтобы authenticated actor был receiver.
- Closed events отклоняют financial mutations.
- User listing visibility-limited, а не full user table dump.

## Storage rules

- Receipt image objects должны оставаться private.
- Clients должны использовать presigned URLs для временного чтения.
- Upload response может вернуть временный presigned URL, но backend не должен сохранять permanent public URL для нового image state.
- Replacements и deletes должны чистить старое storage state.
- Secrets хранятся только в environment variables или managed secret stores.
- Нельзя коммитить `.env`, access keys, private keys, production credentials, database dumps или user data.

## Error handling

Client-facing unexpected failures должны быть generic:

```json
{
  "detail": "Internal server error."
}
```

Server logs должны содержать request context:

- request ID
- method
- path
- status code
- duration
- internal exception type для unexpected failures

## CORS

Allowed origins должны быть явными. Default development и production origins настроены в `app/main.py`; production может переопределять их через `CORS_ALLOWED_ORIGINS`.

## Security checklist перед release

- Запустить `make test`.
- Запустить `make lint`.
- Проверить, что `openapi.yaml` совпадает с route behavior.
- Проверить, что в git нет secrets или user data.
- Проверить, что production CORS origins заданы явно.
- Проверить, что `/api/metrics` имеет `METRICS_ACCESS_TOKEN` и не опубликован наружу без reverse proxy/network policy.
- Проверить encryption at rest для MongoDB и object storage.
- Проверить, что receipt images private и читаются через presigned URLs.
- Запустить dependency audit (`make security-audit`) и secret scan перед production release.
- Пересмотреть [docs/security-baseline.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/security-baseline.md).

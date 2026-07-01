# SplitApp Security Baseline

Этот checklist — базовая security-планка для backend-работы.

## Данные И Legal Hygiene

- До работы с реальными пользователями нужна публичная privacy policy.
- Нужно понимать, где физически хранятся user data: database region, object storage и third-party services.
- Нельзя экспортировать user data в личные инструменты или хранить passwords/secrets plaintext.
- Нельзя вставлять secrets, credentials, private user data или production dumps в AI chats.

## Authentication И Authorization

- Каждый API route должен проверять session и authenticated actor.
- Нельзя авторизовать доступ только по client-supplied user ID.
- Нужны negative auth tests, а не только happy path.
- Sensitive account identifiers не должны раскрываться в ответах, если продукт явно этого не требует.
- Refresh-token behavior должен позволять безопасный retry после потерянного ответа.

## API И Input Safety

- Все write requests валидируются на server: type, length, ranges, ownership и membership.
- Unexpected internal failures возвращают generic user-facing errors.
- Полные exception details логируются только на сервере с request/correlation context.
- Public и expensive endpoints rate-limit'ятся до запуска.
- CORS должен быть explicit allowlist.
- API responses не должны over-fetch sensitive fields.

## Storage И Secrets

- Secret keys живут только в environment variables или managed secret stores.
- Public client keys допустимы только если они действительно designed to be public.
- Перед launch нужно проверить git history на committed `.env` files и secrets.
- Object storage должен поддерживать deletion/replacement и избегать permanent public URLs, когда достаточно presigned URL.
- Нужно подтвердить encryption at rest для managed database и object storage.

## Operations

- Structured logging нужен до production usage.
- Monitoring и alerting нужны до того, как пользователи станут главным источником ошибок.
- Для deploy предпочтительны supervised runtime: systemd или containers, не `nohup`.
- Перед release запускаются lint, tests и security scan.
- Backend fixes и frontend follow-up work отслеживаются отдельно.

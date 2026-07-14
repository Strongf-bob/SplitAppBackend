# P1 Production Rollout

Дата: 2026-07-01.

P1 закрывает backend/API и production-readiness для домена `https://split-app.ru`.
Полноценная iOS/UX-разработка в этот шаг не входит: backend должен отдавать
статичную публичную страницу и защищенный API на актуальном production-домене.

## Scope

- Production API base URL: `https://split-app.ru`.
- Старый домен `splitapp.tech` не использовать в новых настройках.
- Статичная публичная страница должна открываться через `/`.
- `/api/*` остается backend API; защищенные endpoints требуют bearer token.
- P0 safety flows остаются API-first контрактом: receipt review, invite decline,
  confirmation summaries и home summary buckets.

## GitHub setup

Repository settings для `main`:

- включить branch protection;
- требовать PR перед merge;
- требовать успешные checks `lint` и `test`;
- запретить force-push;
- включить production environment для deploy workflow;
- хранить deploy credentials только в GitHub secrets.

Required repository/environment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH`
- optional `DEPLOY_PORT`

## Server prerequisites

DNS для `split-app.ru` должен указывать на production entrypoint до smoke-check.
Если `curl` возвращает `Could not resolve host`, это не backend regression, а
незавершенная DNS/registrar настройка.

На сервере в `DEPLOY_PATH/.env` должны быть заданы:

- `CORS_ALLOWED_ORIGINS=https://split-app.ru`
- `JWT_SECRET`
- MongoDB connection settings
- S3 settings, если включен receipt image flow
- `HOST_PORT`
- `GRAFANA_ADMIN_PASSWORD`
- `METRICS_ACCESS_TOKEN`

Grafana должна оставаться на localhost bind или за reverse proxy с auth/TLS.
Prometheus, Loki и `/api/metrics` нельзя публиковать как пользовательский UI.

## Production smoke checks

После DNS и deploy:

```bash
curl -fsS https://split-app.ru/api/ping
curl -fsS https://split-app.ru/api/health/db
curl -I https://split-app.ru/
```

Expected result:

- `/api/ping` returns `{"message":"pong"}`;
- `/api/health/db` confirms database connectivity;
- web shell routes return `200`;
- manifest and service worker return `200`;
- `/api/metrics` is protected by token/internal network policy when public
  clients reach the service.

## Local validation before PR

```bash
make lint
make test
```

If backend API behavior changes, regenerate or update `openapi.yaml` in the same
change and add regression tests.

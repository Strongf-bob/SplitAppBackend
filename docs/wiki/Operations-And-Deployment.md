# Операции и деплой

P1 production rollout для актуального домена `https://split-app.ru` описан в
[P1 Production Rollout](../p1-production-rollout.md).

## Production Runtime

### Docker Compose

Backend можно запускать как отдельный Docker Compose project:

- [compose.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/compose.yaml)
- [Dockerfile](https://github.com/Strongf-bob/SplitAppBackend/blob/main/Dockerfile)
- [.env.docker.example](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.env.docker.example)

Compose поднимает:

- `api` — FastAPI/uvicorn container, опубликован как `${HOST_PORT:-8080}:8000`.
- `mongo` — private MongoDB container во внутренней network `splitapp-backend`.
- `mongo-data` — persistent Docker volume для database files.

Deploy:

```bash
cp .env.docker.example .env
export JWT_SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
python3 - <<'PY'
from pathlib import Path
import os

path = Path(".env")
value = path.read_text()
value = value.replace(
    "JWT_SECRET=change-me-generate-a-long-random-value",
    f"JWT_SECRET={os.environ['JWT_SECRET']}",
)
path.write_text(value)
PY
docker compose up -d --build
docker compose ps
```

Operational checks:

```bash
curl http://127.0.0.1:${HOST_PORT:-8080}/api/ping
docker compose logs -f api
```

Receipt image endpoints требуют S3 settings в `.env`. Без S3 settings только
upload/delete/presign операции изображений возвращают configuration error.

### Systemd

Для systemd deployment используется unit:

- [deploy/splitapp-backend.service](https://github.com/Strongf-bob/SplitAppBackend/blob/main/deploy/splitapp-backend.service)

Рекомендуемый install path:

- `/opt/splitapp/backend`

Рекомендуемый env file:

- `/etc/splitapp/backend.env`

## Deploy Steps

```bash
sudo cp deploy/splitapp-backend.service /etc/systemd/system/splitapp-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now splitapp-backend
sudo systemctl status splitapp-backend
```

Logs:

```bash
journalctl -u splitapp-backend -f
```

## GitHub Actions Deployment

Основной CI/CD workflow:

- [.github/workflows/ci.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/ci.yml)

На push в `main` workflow запускает lint, tests и затем Docker Compose deploy
over SSH, если настроены production secrets. Workflow отправляет checkout на
сервер tar-архивом, сохраняет существующий server-side `.env`, запускает port
preflight, выполняет `docker compose up -d --build` и проверяет `GET /api/ping`.

Required deployment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH` — например `/home/strongf/splitapp/backend`.
- Optional: `DEPLOY_PORT` — SSH port, default `22`.

Server prerequisites:

- Docker и Docker Compose доступны для `DEPLOY_USER`.
- В `DEPLOY_PATH/.env` уже лежат runtime secrets: `JWT_SECRET`, Mongo/S3 config.
- `HOST_PORT` в `.env` задает host port для smoke check; default `8080`.
- `GRAFANA_ADMIN_PASSWORD` задан в server-side `.env`.
- `GRAFANA_HOST_PORT` задает localhost port для Grafana; default `3001`.
- Перед deploy workflow проверяет, что `HOST_PORT` и `GRAFANA_HOST_PORT` не заняты другим container или host process.

## Runtime Environment Variables

MongoDB:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- или отдельные host/user/password/auth source values.
- TLS и replica set variables для managed clusters.

Object storage:

- `S3_ENDPOINT_URL`
- `S3_REGION`
- `S3_BUCKET`
- `YC_OBJECT_STORAGE_ACCESS_KEY_ID`
- `YC_OBJECT_STORAGE_SECRET_ACCESS_KEY`

Security и app behavior:

- JWT/access token settings, которые используют token helpers.
- `CORS_ALLOWED_ORIGINS`
- Optional Sentry/error reporting configuration.
- Splitik LLM:
  - `SPLITIK_LLM_BASE_URL`
  - `SPLITIK_LLM_API_KEY`
  - `SPLITIK_PRIMARY_MODEL`
  - `SPLITIK_FAST_CHAT_MODEL` - fast model for plain chat replies; default
    `deepseek-v4-flash`.
  - `SPLITIK_FAST_CHAT_TIMEOUT_SECONDS` - default `8`.
  - `SPLITIK_INTENT_MODEL` — optional small routing model; use `deepseek-v4-flash`
    for the pre-planner intent classifier.
  - `SPLITIK_INTENT_TIMEOUT_SECONDS` - optional timeout for the intent router.
  - `SPLITIK_VERIFICATION_MODEL`
  - `SPLITIK_ESCALATION_MODEL`
  - `SPLITIK_LLM_TIMEOUT_SECONDS` - default `12`.
  - `SPLITIK_LLM_MODEL` — legacy fallback только для primary model.

`SPLITIK_LLM_MODEL` или `SPLITIK_PRIMARY_MODEL` достаточно для primary Splitik
replies. Plain chat replies use `SPLITIK_FAST_CHAT_MODEL`; if it is not set,
backend uses `SPLITIK_INTENT_MODEL` or `deepseek-v4-flash`. `SPLITIK_INTENT_MODEL`
можно не задавать, тогда pre-planner intent classifier использует primary
model. AI receipt drafts дополнительно требуют `SPLITIK_VERIFICATION_MODEL` и
`SPLITIK_ESCALATION_MODEL`; если они отсутствуют, configuration error возвращает
только draft endpoint, а backend и обычный Splitik chat продолжают работать.
Model IDs должны жить в environment variables, а не в коде, чтобы provider/model
mix можно было менять без rebuild backend.

CI runs an `LLM Smoke` job on every push before production deploy. The job sends
short health-check requests to configured Splitik model roles and fails if a
model does not answer within its role timeout. Required GitHub secrets are
`SPLITIK_LLM_BASE_URL`, `SPLITIK_LLM_API_KEY`, and `SPLITIK_PRIMARY_MODEL`
(`OCR_LLM_URL`, `OCR_LLM_AUTH_TOKEN`, and `OCR_LLM_MODEL` are accepted as
legacy fallbacks). Optional secrets/vars configure `SPLITIK_FAST_CHAT_MODEL`,
`SPLITIK_INTENT_MODEL`, `SPLITIK_VERIFICATION_MODEL`,
`SPLITIK_ESCALATION_MODEL`, and per-role timeout vars.

PWA:

- `web/` содержит installable SplitApp web client.
- `/`, `/app`, `/manifest.webmanifest`, `/sw.js` и `/assets/*` — public static routes, которые обслуживает FastAPI.
- `/api/*` остается bearer-token protected, кроме documented auth/health exceptions.
- Service worker кеширует только app shell и static assets. Authenticated API responses он не кеширует.

Grafana:

- `GRAFANA_BIND_ADDRESS` — default `127.0.0.1`.
- `GRAFANA_HOST_PORT` — default `3001`.
- `GRAFANA_ADMIN_USER`.
- `GRAFANA_ADMIN_PASSWORD` — required на сервере.
- `GRAFANA_PUBLIC_DOMAIN` — optional public HTTPS hostname for Grafana, for
  example `grafana.split-app.ru`.
- `GRAFANA_PUBLIC_PROXY_MODE` — `external` when the host already owns `443`, or
  `caddy` when Compose should start the bundled Caddy proxy.
- `GRAFANA_PUBLIC_HTTPS_PORT` — default `443` for the public Grafana proxy.

## Metrics

Prometheus metrics:

- `GET /api/metrics`

В Docker Compose Prometheus скрейпит endpoint внутри private network с
`METRICS_ACCESS_TOKEN`. Prometheus и Loki не публикуются на host. Grafana
публикуется только на `${GRAFANA_BIND_ADDRESS:-127.0.0.1}:${GRAFANA_HOST_PORT:-3001}`.
Если `GRAFANA_PUBLIC_DOMAIN` задан и `GRAFANA_PUBLIC_PROXY_MODE=caddy`,
дополнительно стартует Compose profile `public-grafana` с Caddy proxy: наружу
публикуется только `https://${GRAFANA_PUBLIC_DOMAIN}`, а Prometheus, Loki и
`/api/metrics` остаются доступны только внутри private network. Если `443` уже
занят host reverse proxy, используйте `GRAFANA_PUBLIC_PROXY_MODE=external` и
проксируйте этот host proxy на `127.0.0.1:${GRAFANA_HOST_PORT:-3001}`.

Перед ручной сменой портов проверьте listeners:

```bash
ss -ltnp | grep -E ':(${HOST_PORT:-8080}|${GRAFANA_HOST_PORT:-3001}|443)'
```

Если нужен публичный доступ к Grafana, используйте reverse proxy с auth/TLS или
SSH tunnel. Встроенный public proxy использует Grafana login и TLS от Caddy, но
его нельзя включать на host, где `443` уже занят другим reverse proxy. Не
публикуйте `/api/metrics`, Prometheus или Loki напрямую наружу.

Dashboard `SplitApp Backend` включает RPS, 5xx error ratio, p50/p95/p99 latency,
slow endpoints, service/db operations и API logs через Loki.

Дополнительные observability services работают только внутри Compose network:

- `mongodb-exporter` — MongoDB health, connections и operation counters.
- `cadvisor` — container CPU и memory metrics.
- `node-exporter` — host CPU, memory и filesystem metrics.

Backend экспортирует business metrics: domain actions для events, receipts,
payments и users; money amount histograms для receipts/payments; event participant
count histograms; current collection document counts.

## Backup And Restore

Минимальный production baseline:

- MongoDB data volume или managed MongoDB cluster должен иметь регулярные backups.
- Перед destructive deploy или migration нужно иметь свежий restore point.
- Restore drill должен быть проверен отдельно от backup creation.
- RPO/RTO должны быть явно зафиксированы для production; до этого считать систему pre-production.

Для Docker Compose self-hosted MongoDB используйте volume-level snapshots или
`mongodump`/`mongorestore` из trusted host. Backup artifacts должны храниться
зашифрованно, с ограниченным доступом и без копирования в личные устройства.

## Incident Response

Для production incident нужен короткий runbook:

- Зафиксировать время начала, affected endpoint/domain flow и request IDs.
- Снять `docker compose ps`, `docker compose logs api --tail=200` и Grafana/Loki evidence.
- При suspected credential exposure сразу rotate affected secrets: `JWT_SECRET`,
  object storage keys, deploy key, Grafana password и LLM provider token.
- После mitigation записать root cause, customer impact, fixed commit и regression test.

## Data Retention And Privacy

До real-user launch нужны публичная privacy policy и внутренняя retention policy.
Минимальные решения, которые должны быть зафиксированы:

- как долго хранятся users, contacts, events, receipts, receipt images, audit logs и Splitik interactions;
- как пользователь запрашивает export/delete account;
- какие данные уходят в Yandex OAuth, object storage, Sentry и LLM provider;
- где физически хранятся MongoDB/object-storage данные и включено ли encryption at rest.

## Logs

Request middleware пишет structured JSON completion logs с level, request ID,
method, route-template path, raw path, status и duration. Loki получает docker
logs через Grafana Alloy; `request_id` остается JSON field для поиска, но не
становится Loki label. Unexpected exceptions логируются внутри сервера и
возвращаются клиентам как generic errors.

## Operational Checks

- `GET /api/health/db` должен подтверждать MongoDB connectivity.
- `GET /api/metrics` должен возвращать Prometheus text exposition.
- `systemctl status splitapp-backend` должен быть healthy после deploy.
- `journalctl -u splitapp-backend -f` должен показывать request logs и startup failures.

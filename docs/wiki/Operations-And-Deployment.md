# Операции и деплой

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
  - `SPLITIK_VERIFICATION_MODEL`
  - `SPLITIK_ESCALATION_MODEL`
  - `SPLITIK_LLM_TIMEOUT_SECONDS`
  - `SPLITIK_LLM_MODEL` — legacy fallback только для primary model.

`SPLITIK_LLM_MODEL` или `SPLITIK_PRIMARY_MODEL` достаточно для обычных Splitik
chat replies. AI receipt drafts дополнительно требуют `SPLITIK_VERIFICATION_MODEL`
и `SPLITIK_ESCALATION_MODEL`; если они отсутствуют, configuration error возвращает
только draft endpoint, а backend и обычный Splitik chat продолжают работать.
Model IDs должны жить в environment variables, а не в коде, чтобы provider/model
mix можно было менять без rebuild backend.

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

## Metrics

Prometheus metrics:

- `GET /api/metrics`

В Docker Compose Prometheus скрейпит endpoint внутри private network с
`METRICS_ACCESS_TOKEN`. Prometheus и Loki не публикуются на host. Grafana
публикуется только на `${GRAFANA_BIND_ADDRESS:-127.0.0.1}:${GRAFANA_HOST_PORT:-3001}`.

Перед ручной сменой портов проверьте listeners:

```bash
ss -ltnp | grep -E ':(${HOST_PORT:-8080}|${GRAFANA_HOST_PORT:-3001})'
```

Если нужен публичный доступ к Grafana, используйте reverse proxy с auth/TLS или
SSH tunnel. Не публикуйте `/api/metrics`, Prometheus или Loki напрямую наружу.

Dashboard `SplitApp Backend` включает RPS, 5xx error ratio, p50/p95/p99 latency,
slow endpoints, service/db operations и API logs через Loki.

Дополнительные observability services работают только внутри Compose network:

- `mongodb-exporter` — MongoDB health, connections и operation counters.
- `cadvisor` — container CPU и memory metrics.
- `node-exporter` — host CPU, memory и filesystem metrics.

Backend экспортирует business metrics: domain actions для events, receipts,
payments и users; money amount histograms для receipts/payments; event participant
count histograms; current collection document counts.

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

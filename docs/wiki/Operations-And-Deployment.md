# Операции и деплой

## Production runtime

### Docker Compose

Backend можно запускать как отдельный Docker Compose project:

- [compose.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/compose.yaml)
- [Dockerfile](https://github.com/Strongf-bob/SplitAppBackend/blob/main/Dockerfile)
- [.env.docker.example](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.env.docker.example)

Compose поднимает:

- `api` — FastAPI/uvicorn container, published as `${HOST_PORT:-8080}:8000`.
- `mongo` — private MongoDB container in the internal `splitapp-backend` network.
- `mongo-data` — persistent Docker volume for database files.

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

Receipt image endpoints require S3 settings in `.env`. Without S3 settings,
only receipt image upload/delete/presign operations return a configuration
error.

### Systemd

Production deployment должен использовать systemd unit:

- [deploy/splitapp-backend.service](https://github.com/Strongf-bob/SplitAppBackend/blob/main/deploy/splitapp-backend.service)

Recommended install path:

- `/opt/splitapp/backend`

Recommended env file:

- `/etc/splitapp/backend.env`

## Deploy steps

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

## GitHub Actions deployment

Основной CI/CD workflow:

- [.github/workflows/ci.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/ci.yml)

На push в `main` workflow запускает lint, tests и затем Docker Compose deploy
over SSH, если настроены production secrets. Workflow отправляет checkout на
сервер tar-архивом, сохраняет существующий server-side `.env`, запускает
port preflight, запускает `docker compose up -d --build` и проверяет
`GET /api/ping`.

Required deployment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH` — например `/home/strongf/splitapp/backend`.
- Optional: `DEPLOY_PORT` — SSH port, defaults to `22`.

Server prerequisites:

- Docker и Docker Compose доступны для `DEPLOY_USER`.
- В `DEPLOY_PATH/.env` уже лежат runtime secrets (`JWT_SECRET`, Mongo/S3 config).
- `HOST_PORT` в `.env` задает host port для smoke check; default `8080`.
- `GRAFANA_ADMIN_PASSWORD` задан в server-side `.env`.
- `GRAFANA_HOST_PORT` задает localhost port для Grafana; default `3001`.
- Перед deploy workflow проверяет, что `HOST_PORT` и `GRAFANA_HOST_PORT` не заняты
  другим контейнером или host process.

## Runtime environment variables

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

- JWT/access token settings, используемые token helpers.
- `CORS_ALLOWED_ORIGINS`
- Optional Sentry/error reporting configuration.
- Grafana:
  - `GRAFANA_BIND_ADDRESS` — default `127.0.0.1`.
  - `GRAFANA_HOST_PORT` — default `3001`.
  - `GRAFANA_ADMIN_USER`.
  - `GRAFANA_ADMIN_PASSWORD` — required on the server.

## Metrics

Prometheus metrics:

- `GET /api/metrics`

В Docker Compose Prometheus скрейпит этот endpoint внутри private network.
Prometheus и Loki не публикуются на host. Grafana публикуется только на
`${GRAFANA_BIND_ADDRESS:-127.0.0.1}:${GRAFANA_HOST_PORT:-3001}`.

Перед ручным изменением портов проверьте listeners:

```bash
ss -ltnp | grep -E ':(${HOST_PORT:-8080}|${GRAFANA_HOST_PORT:-3001})'
```

Если нужен публичный доступ к Grafana, используйте reverse proxy с auth/TLS или
SSH tunnel. Не публикуйте `/api/metrics`, Prometheus или Loki напрямую наружу.

Dashboard `SplitApp Backend` включает RPS, 5xx error ratio, p50/p95/p99 latency,
slow endpoints, service/db operations и API logs через Loki.

Additional observability services run inside the Compose network only:

- `mongodb-exporter` — MongoDB health, connections and operation counters.
- `cadvisor` — container CPU and memory metrics.
- `node-exporter` — host CPU, memory and filesystem metrics.

Business metrics exported by the backend include domain actions for events,
receipts, payments and users; money amount histograms for receipts/payments;
event participant count histograms; and current collection document counts.

## Logs

Request middleware пишет structured JSON completion logs с level, request ID,
method, route-template path, raw path, status и duration. Loki получает docker
logs через Grafana Alloy; `request_id` остается полем JSON для поиска, но не
становится Loki label. Unexpected exceptions логируются внутри сервера и
возвращаются клиентам как generic errors.

## Operational checks

- `GET /api/health/db` должен подтверждать MongoDB connectivity.
- `GET /api/metrics` должен возвращать Prometheus text exposition.
- `systemctl status splitapp-backend` должен быть healthy после deploy.
- `journalctl -u splitapp-backend -f` должен показывать request logs и startup failures.

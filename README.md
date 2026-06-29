# SplitAppBackend

## Run locally

1. Create/update virtual environment and install dependencies:

   `make setup`

2. Create your local env file:

   `cp .env.example .env`

3. Fill `.env` with your MongoDB values:

   Option A (full connection string, recommended):

   `MONGODB_URI=mongodb://username:password@localhost:27017/?authSource=admin`

   Option B (separate values; app builds the URI for you):

   `MONGODB_HOST=localhost`

   `MONGODB_PORT=27017`

   `MONGODB_USER=username`

   `MONGODB_PASSWORD=password`

   `MONGODB_AUTH_SOURCE=admin`

   `MONGODB_DB_NAME=splitapp`

   Option C (managed cluster, replica set + TLS; similar to your hosting example):

   `MONGODB_HOSTS=rc1b-4ukf7rtvtpealt1c.mdb.yandexcloud.net:27018`

   `MONGODB_USER=split-app`

   `MONGODB_PASSWORD=<your-password>`

   `MONGODB_DB_NAME=split-app`

   `MONGODB_AUTH_SOURCE=split-app`

   `MONGODB_REPLICA_SET=rs01`

   `MONGODB_TLS=true`

   `MONGODB_TLS_CA_FILE=/home/<your-home>/.mongodb/root.crt`

4. Start the API:

   `make run-dev`

The login handler is available at `POST /api/login`.
MongoDB connection health is available at `GET /api/health/db`.

## Run on remote server

### Docker Compose

The backend can run in an isolated Docker Compose project with private MongoDB,
Prometheus, and Loki containers. Only the API port and localhost-bound Grafana
port are published to the host.

1. `cp .env.docker.example .env`
2. Generate a long random `JWT_SECRET` and update `.env`.
3. Optionally change `HOST_PORT` if `8080` is already used.
4. Set `GRAFANA_ADMIN_PASSWORD` to a long random value.
5. Optionally change `GRAFANA_HOST_PORT` if `3001` is already used.
6. `docker compose up -d --build`
7. `docker compose ps`

The API listens on `http://<server-ip>:${HOST_PORT:-8080}`. MongoDB data is kept
in the `mongo-data` Docker volume and is not exposed outside the Compose network.
Prometheus and Loki are internal-only services. Grafana binds to
`127.0.0.1:${GRAFANA_HOST_PORT:-3001}` by default; use an SSH tunnel or a
reverse proxy with authentication instead of exposing all observability ports.

Before changing ports on a shared server, check listeners:

`ss -ltnp | grep -E ':(${HOST_PORT:-8080}|${GRAFANA_HOST_PORT:-3001})'`

Receipt image endpoints require S3 settings in `.env`; without them, those
endpoints return a configuration error while the rest of the API remains usable.

GitHub Actions deploy uses the same Compose runtime on pushes to `main`. Configure
`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, and `DEPLOY_PATH` repository
secrets; keep production runtime secrets and Grafana credentials in the
server-side `.env`.

### Systemd

For production, prefer the systemd unit in `deploy/splitapp-backend.service`.
Install the app under `/opt/splitapp/backend`, put environment variables in
`/etc/splitapp/backend.env`, then enable the service:

1. `sudo cp deploy/splitapp-backend.service /etc/systemd/system/splitapp-backend.service`
2. `sudo systemctl daemon-reload`
3. `sudo systemctl enable --now splitapp-backend`
4. `sudo systemctl status splitapp-backend`

Logs are available through `journalctl -u splitapp-backend -f`.

The legacy Make target still starts the app in the background for quick manual checks:

1. `make setup`
2. `make run`

Defaults:
- Host: `0.0.0.0`
- Port: `8000`

You can override port/host:

`PORT=8080 HOST=0.0.0.0 make run`

Useful process commands:

- `make status`
- `make logs`
- `make stop`

You can also override MongoDB settings inline:

`MONGODB_URI="mongodb://username:password@localhost:27017/?authSource=admin" MONGODB_DB_NAME="splitapp" make run`

## Manual venv commands (optional)

If you prefer to run commands manually:

1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `uvicorn main:app --host 0.0.0.0 --port 8000`

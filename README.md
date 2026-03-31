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

Use the production-style target (binds to all interfaces and survives SSH disconnect):

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
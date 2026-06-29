# Local Setup

## Requirements

- Python 3.
- MongoDB reachable from the local machine.
- A `.env` file with MongoDB settings.
- Optional S3-compatible object storage variables if testing receipt image uploads against real storage.

## Install Dependencies

```bash
make setup
```

This creates `.venv` and installs `requirements.txt`.

## Configure Environment

Create a local env file:

```bash
cp .env.example .env
```

Then fill MongoDB settings. The backend supports either a full URI or separate values.

### Option A: Full MongoDB URI

```env
MONGODB_URI=mongodb://username:password@localhost:27017/?authSource=admin
MONGODB_DB_NAME=splitapp
```

### Option B: Separate MongoDB Values

```env
MONGODB_HOST=localhost
MONGODB_PORT=27017
MONGODB_USER=username
MONGODB_PASSWORD=password
MONGODB_AUTH_SOURCE=admin
MONGODB_DB_NAME=splitapp
```

### Option C: Managed MongoDB With TLS

```env
MONGODB_HOSTS=rc1b-4ukf7rtvtpealt1c.mdb.yandexcloud.net:27018
MONGODB_USER=split-app
MONGODB_PASSWORD=<your-password>
MONGODB_DB_NAME=split-app
MONGODB_AUTH_SOURCE=split-app
MONGODB_REPLICA_SET=rs01
MONGODB_TLS=true
MONGODB_TLS_CA_FILE=/home/<your-home>/.mongodb/root.crt
```

## Run Development Server

```bash
make run-dev
```

Default URL:

- `http://localhost:8000`

Useful endpoints:

- `POST /api/login`
- `GET /api/health/db`
- `GET /api/metrics`

## Manual Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Background Run For Quick Checks

```bash
make run
make status
make logs
make stop
```

Override host or port:

```bash
PORT=8080 HOST=0.0.0.0 make run
```

## Local iOS Connection

The iOS client currently uses `https://splitapp.tech` in `APIClient`. For local backend testing, the iOS repository should expose a development base URL switch instead of hard-coding production. See [iOS Frontend Integration](iOS-Frontend-Integration).


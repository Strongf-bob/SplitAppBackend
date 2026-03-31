# SplitAppBackend

## Run locally

1. Create/update virtual environment and install dependencies:

   `make setup`

2. Start the API:

   `make run-dev`

The login handler is available at `POST /api/login`.

## Run on remote server

Use the production-style target (binds to all interfaces):

1. `make setup`
2. `make run`

Defaults:
- Host: `0.0.0.0`
- Port: `8000`

You can override port/host:

`PORT=8080 HOST=0.0.0.0 make run`

## Manual venv commands (optional)

If you prefer to run commands manually:

1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `uvicorn main:app --host 0.0.0.0 --port 8000`
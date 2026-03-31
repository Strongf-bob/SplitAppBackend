# SplitAppBackend

## Run locally

1. Create/update virtual environment and install dependencies:

   `make setup`

2. Start the API:

   `make run`

The login handler is available at `POST /api/login`.

## Manual venv commands (optional)

If you prefer to run commands manually:

1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `uvicorn main:app --reload`
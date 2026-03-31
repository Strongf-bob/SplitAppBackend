from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from mongodb import (
    close_mongodb,
    connect_mongodb,
    load_env_file,
    ping_mongodb,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_env_file()
        connect_mongodb(app)
    except Exception as exc:
        raise RuntimeError("Could not connect to MongoDB with current settings.") from exc

    yield

    close_mongodb(app)


app = FastAPI(lifespan=lifespan)


@app.get("/api/health/db")
def db_health() -> dict[str, str]:
    try:
        ping_mongodb(app)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="MongoDB ping failed") from exc
    return {"message": "MongoDB connected"}


@app.post("/api/login")
def login() -> dict[str, str]:
    return {"message": "Hello, world!"}

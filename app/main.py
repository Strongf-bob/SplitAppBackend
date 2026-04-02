from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.db import close_mongodb, connect_mongodb, load_env_file
from app.routers import (
    events_router,
    health_router,
    payments_router,
    receipts_router,
    users_router,
)
from app.services import ensure_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_env_file()
        connect_mongodb(app)
        ensure_indexes(app.state.db)
    except Exception as exc:
        raise RuntimeError("Could not connect to MongoDB with current settings.") from exc

    yield

    close_mongodb(app)


def create_app() -> FastAPI:
    api = FastAPI(lifespan=lifespan, title="SplitApp Backend")
    api.include_router(health_router)
    api.include_router(users_router)
    api.include_router(events_router)
    api.include_router(receipts_router)
    api.include_router(payments_router)
    return api


app = create_app()


from contextlib import asynccontextmanager
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.db import close_mongodb, connect_mongodb, load_env_file
from app.core.s3 import connect_s3
from app.dependencies import require_auth_token
from app.routers import (
    auth_router,
    events_router,
    health_router,
    payments_router,
    receipts_router,
    users_router,
)
from app.services import ensure_indexes

DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://splitapp.tech",
)


def cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ALLOWED_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def configure_cors(api: FastAPI) -> None:
    api.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_env_file()
        connect_mongodb(app)
        connect_s3(app)
        ensure_indexes(app.state.db)
    except Exception as exc:
        raise RuntimeError("Could not connect to MongoDB with current settings.") from exc

    yield

    close_mongodb(app)


def create_app() -> FastAPI:
    api = FastAPI(
        lifespan=lifespan,
        title="SplitApp Backend",
        dependencies=[Depends(require_auth_token)],
    )
    api.include_router(health_router)
    api.include_router(auth_router)
    api.include_router(events_router)
    api.include_router(users_router)
    api.include_router(receipts_router)
    api.include_router(payments_router)
    configure_cors(api)
    return api


app = create_app()

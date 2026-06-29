from contextlib import asynccontextmanager
import json
import logging
import os
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

logger = logging.getLogger("splitapp")

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


def _log_json(level: int, message: str, **fields: object) -> None:
    logger.log(level, json.dumps({"message": message, **fields}, default=str))


def configure_exception_handlers(api: FastAPI) -> None:
    @api.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or str(uuid4())
        _log_json(
            logging.ERROR,
            "unhandled_request_error",
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
            headers={"X-Request-ID": request_id},
        )


def configure_request_logging(api: FastAPI) -> None:
    @api.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = time.monotonic()

        response = await call_next(request)
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        _log_json(
            logging.INFO,
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


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
    configure_exception_handlers(api)
    configure_request_logging(api)
    configure_cors(api)
    return api


app = create_app()

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
from pathlib import Path
import time
from typing import Callable
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.db import close_mongodb, connect_mongodb, load_env_file
from app.core.monitoring import init_sentry, record_request_metrics
from app.core.s3 import connect_s3
from app.dependencies import require_auth_token
from app.routers import (
    audit_router,
    avatars_router,
    auth_router,
    client_reports_router,
    disputes_router,
    events_router,
    friends_router,
    health_router,
    home_router,
    payments_router,
    receipts_router,
    reports_router,
    splitik_router,
    users_router,
)
from app.services import ensure_indexes
from app.services import splitik_llm

logger = logging.getLogger("splitapp")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LANDING_ROOT = PROJECT_ROOT / "app" / "static" / "landing"
PUBLIC_DOCS_ROOT = PROJECT_ROOT / "docs" / "business-logic-site"

DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://split-app.ru",
)
GRAFANA_PROXY_PATH = "/grafana"
GRAFANA_INTERNAL_URL = "http://grafana:3000"
PROXY_REQUEST_EXCLUDED_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
PROXY_RESPONSE_EXCLUDED_HEADERS = PROXY_REQUEST_EXCLUDED_HEADERS | {
    "content-encoding",
}


def cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    origins = (
        list(DEFAULT_CORS_ALLOWED_ORIGINS)
        if not raw
        else [origin.strip() for origin in raw.split(",") if origin.strip()]
    )
    if "https://split-app.ru" in origins and "https://www.split-app.ru" not in origins:
        origins.append("https://www.split-app.ru")
    return origins


def configure_cors(api: FastAPI) -> None:
    api.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )


def _log_json(level: int, message: str, **fields: object) -> None:
    logger.log(
        level,
        json.dumps(
            {"level": logging.getLevelName(level), "message": message, **fields}, default=str
        ),
    )


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return "__unmatched__"


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
        status_code = 500
        route_path = "__unmatched__"

        try:
            response = await call_next(request)
            status_code = response.status_code
            route_path = _route_template(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_seconds = time.monotonic() - started
            duration_ms = round(duration_seconds * 1000, 2)
            record_request_metrics(request.method, route_path, status_code, duration_seconds)
            _log_json(
                logging.INFO,
                "request_completed",
                request_id=request_id,
                method=request.method,
                path=route_path,
                raw_path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            )


def configure_landing_site(api: FastAPI) -> None:
    assets_root = LANDING_ROOT / "assets"
    if assets_root.exists():
        api.mount("/assets/landing", StaticFiles(directory=assets_root), name="landing-assets")

    @api.get("/", include_in_schema=False)
    @api.head("/", include_in_schema=False)
    async def landing_page() -> FileResponse:
        return FileResponse(LANDING_ROOT / "index.html")


def configure_public_docs(api: FastAPI) -> None:
    if not PUBLIC_DOCS_ROOT.exists():
        return

    api.mount(
        "/business-logic",
        StaticFiles(directory=PUBLIC_DOCS_ROOT, html=True),
        name="business-logic-docs",
    )


def configure_grafana_proxy(
    api: FastAPI,
    *,
    grafana_base_url: str | None = None,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> None:
    base_url = (
        grafana_base_url or os.getenv("GRAFANA_INTERNAL_URL") or GRAFANA_INTERNAL_URL
    ).rstrip("/")

    @api.get(GRAFANA_PROXY_PATH, include_in_schema=False)
    @api.head(GRAFANA_PROXY_PATH, include_in_schema=False)
    async def grafana_redirect() -> RedirectResponse:
        return RedirectResponse(f"{GRAFANA_PROXY_PATH}/")

    @api.api_route(
        f"{GRAFANA_PROXY_PATH}/{{path:path}}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def grafana_proxy(request: Request, path: str) -> Response:
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in PROXY_REQUEST_EXCLUDED_HEADERS
        }
        headers["accept-encoding"] = "identity"
        headers["x-forwarded-host"] = request.headers.get(
            "x-forwarded-host"
        ) or request.headers.get("host", "")
        headers["x-forwarded-proto"] = (
            request.headers.get("x-forwarded-proto") or request.url.scheme
        )
        headers["x-forwarded-prefix"] = GRAFANA_PROXY_PATH
        if request.client:
            forwarded_for = request.headers.get("x-forwarded-for")
            headers["x-forwarded-for"] = (
                f"{forwarded_for}, {request.client.host}" if forwarded_for else request.client.host
            )

        try:
            async with client_factory(timeout=30.0, follow_redirects=False) as client:
                upstream = await client.request(
                    request.method,
                    f"{base_url}{GRAFANA_PROXY_PATH}/{path}",
                    params=request.query_params.multi_items(),
                    content=await request.body(),
                    headers=headers,
                )
        except httpx.HTTPError:
            logger.exception("grafana_proxy_request_failed", extra={"path": path})
            return JSONResponse(status_code=502, content={"detail": "Grafana is unavailable."})

        response = Response(content=upstream.content, status_code=upstream.status_code)
        for name, value in upstream.headers.multi_items():
            if name.lower() not in PROXY_RESPONSE_EXCLUDED_HEADERS:
                response.headers.append(name, value)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_env_file()
        init_sentry()
        connect_mongodb(app)
        connect_s3(app)
        ensure_indexes(app.state.db)
        splitik_llm.validate_configured_models_available()
    except Exception as exc:
        raise RuntimeError("Could not connect to MongoDB with current settings.") from exc

    async def probe_splitik_model_pools() -> None:
        while True:
            try:
                await asyncio.to_thread(splitik_llm.probe_model_pools)
            except Exception:
                logger.exception("splitik_model_pool_probe_failed")
            await asyncio.sleep(600)

    splitik_probe_task = asyncio.create_task(probe_splitik_model_pools())
    try:
        yield
    finally:
        splitik_probe_task.cancel()
        with suppress(asyncio.CancelledError):
            await splitik_probe_task

    close_mongodb(app)


def create_app() -> FastAPI:
    api = FastAPI(
        lifespan=lifespan,
        title="SplitApp Backend",
        dependencies=[Depends(require_auth_token)],
    )
    api.include_router(health_router)
    api.include_router(home_router)
    api.include_router(audit_router)
    api.include_router(avatars_router)
    api.include_router(auth_router)
    api.include_router(client_reports_router)
    api.include_router(disputes_router)
    api.include_router(events_router)
    api.include_router(friends_router)
    api.include_router(users_router)
    api.include_router(receipts_router)
    api.include_router(payments_router)
    api.include_router(reports_router)
    api.include_router(splitik_router)
    configure_exception_handlers(api)
    configure_request_logging(api)
    configure_cors(api)
    configure_grafana_proxy(api)
    configure_public_docs(api)
    configure_landing_site(api)
    return api


app = create_app()

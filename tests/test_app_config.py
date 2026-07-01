import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.monitoring import metrics_response, monitor_db_operation, monitor_service_operation
from app.core.monitoring import record_domain_event, refresh_database_metrics
from app.dependencies import _is_internal_client, require_auth_token
from app.main import configure_cors, configure_pwa, cors_allowed_origins
from app.main import configure_exception_handlers, configure_request_logging
from app.routers.health import router as health_router


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cors_allowed_origins_parse_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example, https://b.example,,")

    assert cors_allowed_origins() == ["https://a.example", "https://b.example"]


def test_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example")
    api = FastAPI()
    configure_cors(api)

    @api.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(api)
    response = client.options(
        "/ping",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Idempotency-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert "Idempotency-Key" in response.headers["access-control-allow-headers"]


def test_cors_rejects_unconfigured_origin(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example")
    api = FastAPI()
    configure_cors(api)

    @api.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(api)
    response = client.options(
        "/ping",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_unhandled_errors_return_generic_500():
    api = FastAPI()
    configure_exception_handlers(api)
    configure_request_logging(api)

    @api.get("/boom")
    def boom():
        raise RuntimeError("database password leaked")

    client = TestClient(api, raise_server_exceptions=False)
    response = client.get("/boom", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert response.headers["X-Request-ID"] == "req-123"


def test_metrics_endpoint_exposes_prometheus_payload():
    api = FastAPI()
    api.include_router(health_router)

    client = TestClient(api)
    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert "splitapp_http_requests_total" in response.text


def test_metrics_endpoint_requires_metrics_token(monkeypatch):
    monkeypatch.setenv("METRICS_ACCESS_TOKEN", "metrics-secret")
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.include_router(health_router)

    client = TestClient(api)
    response = client.get("/api/metrics")

    assert response.status_code == 404


def test_metrics_endpoint_accepts_metrics_token(monkeypatch):
    monkeypatch.setenv("METRICS_ACCESS_TOKEN", "metrics-secret")
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.include_router(health_router)

    client = TestClient(api)
    response = client.get("/api/metrics", headers={"Authorization": "Bearer metrics-secret"})

    assert response.status_code == 200
    assert "splitapp_http_requests_total" in response.text


def test_non_api_paths_are_public_for_pwa_shell():
    api = FastAPI(dependencies=[Depends(require_auth_token)])

    @api.get("/app")
    def app_shell() -> dict[str, str]:
        return {"app": "splitapp"}

    client = TestClient(api)
    response = client.get("/app")

    assert response.status_code == 200
    assert response.json() == {"app": "splitapp"}


def test_api_paths_still_require_bearer_token():
    api = FastAPI(dependencies=[Depends(require_auth_token)])

    @api.get("/api/protected")
    def protected() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(api)
    response = client.get("/api/protected")

    assert response.status_code == 401


def test_pwa_static_routes_are_registered():
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    configure_pwa(api)

    client = TestClient(api)

    assert client.get("/").status_code == 200
    assert client.get("/app").status_code == 200
    assert client.get("/app/events/demo").status_code == 200
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["short_name"] == "SplitApp"
    service_worker = client.get("/sw.js")
    assert service_worker.status_code == 200
    assert "CACHE_NAME" in service_worker.text
    app_asset = client.get("/assets/app.js")
    assert app_asset.status_code == 200
    assert "bootstrap" in app_asset.text


def test_pwa_static_routes_support_head_smoke_checks():
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    configure_pwa(api)

    client = TestClient(api)

    assert client.head("/").status_code == 200
    assert client.head("/app").status_code == 200
    assert client.head("/app/events/demo").status_code == 200
    assert client.head("/manifest.webmanifest").status_code == 200
    assert client.head("/sw.js").status_code == 200
    assert client.head("/assets/app.js").status_code == 200


def test_docker_image_includes_pwa_assets():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()

    assert "COPY web ./web" in dockerfile


def test_pwa_uses_yandex_oauth_button_instead_of_manual_token_field():
    index_html = (PROJECT_ROOT / "web" / "index.html").read_text()
    app_js = (PROJECT_ROOT / "web" / "assets" / "app.js").read_text()

    assert "yandexLoginButton" in index_html
    assert "Войти через Яндекс" in index_html
    assert "yandexTokenInput" not in index_html
    assert "6c5725f5868c4604adaea1e4b892c14d" in app_js
    assert "https://split-app.ru/app" in app_js
    assert "https://oauth.yandex.ru/authorize" in app_js
    assert "access_token" in app_js
    assert "POST" in app_js
    assert "/api/login" in app_js


def test_operations_scrape_allows_private_and_loopback_clients():
    assert _is_internal_client("127.0.0.1")
    assert _is_internal_client("172.20.0.6")
    assert _is_internal_client("10.0.0.10")


def test_operations_scrape_rejects_public_clients():
    assert not _is_internal_client("8.8.8.8")
    assert not _is_internal_client("1.1.1.1")
    assert not _is_internal_client(None)


def test_request_metrics_use_route_template_not_raw_path():
    api = FastAPI()
    configure_request_logging(api)

    @api.get("/items/{item_id}")
    def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    client = TestClient(api)
    response = client.get("/items/raw-id-123")

    assert response.status_code == 200
    body, _ = metrics_response()
    metrics = body.decode()
    assert 'path="/items/{item_id}"' in metrics
    assert "raw-id-123" not in metrics


def test_request_logs_are_structured_for_loki(caplog):
    api = FastAPI()
    configure_request_logging(api)

    @api.get("/items/{item_id}")
    def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    client = TestClient(api)
    with caplog.at_level(logging.INFO, logger="splitapp"):
        response = client.get("/items/raw-id-456", headers={"X-Request-ID": "req-456"})

    assert response.status_code == 200
    request_log = json.loads(caplog.records[-1].message)
    assert request_log["level"] == "INFO"
    assert request_log["message"] == "request_completed"
    assert request_log["request_id"] == "req-456"
    assert request_log["method"] == "GET"
    assert request_log["path"] == "/items/{item_id}"
    assert request_log["raw_path"] == "/items/raw-id-456"
    assert request_log["status_code"] == 200
    assert isinstance(request_log["duration_ms"], float)


def test_operation_metrics_record_success_and_error():
    with monitor_service_operation("tests.service_success"):
        pass

    try:
        with monitor_db_operation("tests.db_error"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    body, _ = metrics_response()
    metrics = body.decode()
    assert (
        'splitapp_service_operations_total{operation="tests.service_success",status="success"}'
        in metrics
    )
    assert 'splitapp_db_operations_total{operation="tests.db_error",status="error"}' in metrics


def test_domain_and_collection_metrics_are_exported(db):
    db.users.insert_one({"id": "user-1"})
    db.events.insert_one({"id": "event-1"})
    db.events.insert_one({"id": "event-2", "deleted_at": "2026-01-01T00:00:00Z"})
    record_domain_event("tests", "created")
    refresh_database_metrics(db)

    body, _ = metrics_response()
    metrics = body.decode()
    assert 'splitapp_domain_events_total{action="created",domain="tests"}' in metrics
    assert 'splitapp_collection_documents{collection="users",state="all"} 1.0' in metrics
    assert 'splitapp_collection_documents{collection="events",state="active"} 1.0' in metrics
    assert 'splitapp_collection_documents{collection="events",state="deleted"} 1.0' in metrics

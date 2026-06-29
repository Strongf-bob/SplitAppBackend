import json
import logging

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.monitoring import metrics_response, monitor_db_operation, monitor_service_operation
from app.dependencies import _is_internal_client, require_auth_token
from app.main import configure_cors, cors_allowed_origins
from app.main import configure_exception_handlers, configure_request_logging
from app.routers.health import router as health_router


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
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"


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

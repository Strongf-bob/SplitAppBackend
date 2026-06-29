from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import configure_cors, cors_allowed_origins


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

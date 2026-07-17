from datetime import UTC, datetime
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app import main as app_main, schemas
from app.core import tokens
from app.core.monitoring import metrics_response, monitor_db_operation, monitor_service_operation
from app.core.monitoring import record_domain_event, refresh_database_metrics
from app.dependencies import _is_internal_client, get_db, require_auth_token
from app.main import configure_cors, configure_public_docs, cors_allowed_origins
from app.main import configure_exception_handlers, configure_request_logging
from app.routers.client_reports import router as client_reports_router
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.services import indexes, receipts
from tests.conftest import EVENT_ID, USER_A, USER_B, USER_C, confirm_receipt_for_all, seed_event


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def add_cycle_member(db) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.event_memberships.insert_one(
        {
            "id": "aaaaaaaa-0000-0000-0000-000000000003",
            "event_id": EVENT_ID,
            "user_id": USER_C,
            "role": "member",
            "status": "active",
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )


def create_cycle_source(db) -> None:
    seed_event(db)
    add_cycle_member(db)
    first = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="A paid for B",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="AB",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    second = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_B,
            title="B paid for C",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="BC",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_B,
    )
    confirm_receipt_for_all(db, first["id"], USER_A)
    confirm_receipt_for_all(db, second["id"], USER_B)


def test_cors_allowed_origins_parse_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example, https://b.example,,")

    assert cors_allowed_origins() == ["https://a.example", "https://b.example"]


def test_cors_allows_www_alias_for_split_app_production_origin(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://split-app.ru")

    assert cors_allowed_origins() == ["https://split-app.ru", "https://www.split-app.ru"]


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


@pytest.mark.anyio
async def test_lifespan_validates_splitik_models(monkeypatch):
    api = FastAPI()
    calls = []

    monkeypatch.setattr(app_main, "load_env_file", lambda: calls.append("env"))
    monkeypatch.setattr(app_main, "init_sentry", lambda: calls.append("sentry"))
    monkeypatch.setattr(
        app_main,
        "connect_mongodb",
        lambda app: (calls.append("mongo"), setattr(app.state, "db", object())),
    )
    monkeypatch.setattr(app_main, "connect_s3", lambda app: calls.append("s3"))
    monkeypatch.setattr(app_main, "ensure_indexes", lambda db: calls.append("indexes"))
    monkeypatch.setattr(app_main, "close_mongodb", lambda app: calls.append("close"))
    monkeypatch.setattr(
        app_main.splitik_llm,
        "validate_configured_models_available",
        lambda: calls.append("models"),
    )

    async with app_main.lifespan(api):
        calls.append("served")

    assert calls == ["env", "sentry", "mongo", "s3", "indexes", "models", "served", "close"]


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


def test_non_api_paths_are_public():
    api = FastAPI(dependencies=[Depends(require_auth_token)])

    @api.get("/app")
    def app_shell() -> dict[str, str]:
        return {"app": "splitapp"}

    client = TestClient(api)
    response = client.get("/app")

    assert response.status_code == 200
    assert response.json() == {"app": "splitapp"}


def test_grafana_proxy_forwards_same_origin_subpath():
    configure_grafana_proxy = getattr(app_main, "configure_grafana_proxy", None)
    assert callable(configure_grafana_proxy), "Grafana proxy is not configured"

    upstream = FastAPI()

    @upstream.api_route("/{path:path}", methods=["GET", "POST"])
    async def grafana_upstream(request: Request, path: str) -> JSONResponse:
        return JSONResponse(
            status_code=201,
            content={
                "path": path,
                "query": request.url.query,
                "prefix": request.headers.get("x-forwarded-prefix"),
                "host": request.headers.get("x-forwarded-host"),
                "body": (await request.body()).decode(),
            },
            headers={"X-Grafana-Test": "proxied"},
        )

    def client_factory(**kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), **kwargs)

    api = FastAPI(dependencies=[Depends(require_auth_token)])
    configure_grafana_proxy(
        api,
        grafana_base_url="http://grafana:3000",
        client_factory=client_factory,
    )
    client = TestClient(api)

    response = client.post("/grafana/api/search?query=latency", content="dashboard")

    assert response.status_code == 201
    assert response.headers["x-grafana-test"] == "proxied"
    assert response.json() == {
        "path": "grafana/api/search",
        "query": "query=latency",
        "prefix": "/grafana",
        "host": "testserver",
        "body": "dashboard",
    }


def test_grafana_proxy_redirects_bare_path():
    configure_grafana_proxy = getattr(app_main, "configure_grafana_proxy", None)
    assert callable(configure_grafana_proxy), "Grafana proxy is not configured"

    api = FastAPI()
    configure_grafana_proxy(api)
    client = TestClient(api, follow_redirects=False)

    response = client.get("/grafana")

    assert response.status_code == 307
    assert response.headers["location"] == "/grafana/"


def test_api_paths_still_require_bearer_token():
    api = FastAPI(dependencies=[Depends(require_auth_token)])

    @api.get("/api/protected")
    def protected() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(api)
    response = client.get("/api/protected")

    assert response.status_code == 401


def test_public_docs_are_served_without_auth():
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    configure_public_docs(api)

    client = TestClient(api)

    index = client.get("/business-logic/")
    assert index.status_code == 200
    assert "Как SplitApp управляет событиями, чеками, долгами и правами" in index.text
    assert client.get("/business-logic/api-map.html").status_code == 200
    stylesheet = client.get("/business-logic/assets/decisions.css")
    assert stylesheet.status_code == 200
    assert ":root" in stylesheet.text


def test_docker_image_includes_static_landing_assets():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()

    assert "FROM node" not in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY web ./web" not in dockerfile
    assert "COPY docs ./docs" in dockerfile


def test_static_landing_is_public_and_retired_routes_are_absent():
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    app_main.configure_landing_site(api)
    client = TestClient(api)

    root = client.get("/")

    assert root.status_code == 200
    assert "SplitApp" in root.text
    assert "Делите общие расходы" in root.text
    assert client.head("/").status_code == 200
    assert client.get("/assets/landing/landing.css").status_code == 200
    assert client.get("/assets/landing/hero-phone.png").status_code == 200
    assert client.get("/app").status_code == 404
    assert client.get("/manifest.webmanifest").status_code == 404
    assert client.get("/sw.js").status_code == 404


def test_openapi_exposes_domain_enums_for_write_payloads():
    schema = app_main.app.openapi()["components"]["schemas"]

    event_create = schema["EventCreate"]["properties"]
    user_update = schema["UserUpdate"]["properties"]
    dispute_create = schema["DisputeCreate"]["properties"]
    splitik_message = schema["SplitikMessageRequest"]["properties"]

    assert set(event_create["split_strategy"]["enum"]) == {
        "equal_default",
        "itemized_creator",
        "itemized_self_select",
        "agent_assisted",
    }
    assert set(event_create["receipt_creation_policy"]["enum"]) == {
        "creator_only",
        "participants_can_add",
    }
    assert set(user_update["payment_phone_visibility"]["anyOf"][0]["enum"]) == {
        "nobody",
        "event_members",
        "friends",
    }
    assert set(dispute_create["resource_type"]["enum"]) == {
        "receipt",
        "payment",
        "payment_request",
    }
    assert set(splitik_message["mode"]["enum"]) == {"general", "event", "receipt", "member"}


def test_openapi_bounds_user_controlled_write_strings():
    schema = app_main.app.openapi()["components"]["schemas"]

    assert schema["UserUpdate"]["properties"]["name"]["anyOf"][0]["maxLength"] == 120
    assert schema["UserUpdate"]["properties"]["email"]["anyOf"][0]["maxLength"] == 254
    assert schema["UserUpdate"]["properties"]["avatar_url"]["anyOf"][0]["maxLength"] == 500
    assert schema["UserUpdate"]["properties"]["payment_phone"]["anyOf"][0]["maxLength"] == 32
    assert schema["EventCreate"]["properties"]["name"]["maxLength"] == 120
    assert schema["EventUpdate"]["properties"]["name"]["anyOf"][0]["maxLength"] == 120
    assert schema["CreateReceiptItemRequest-Input"]["properties"]["name"]["maxLength"] == 160
    assert schema["CreateReceiptRequest-Input"]["properties"]["title"]["maxLength"] == 160
    assert schema["UpdateReceiptRequest"]["properties"]["title"]["anyOf"][0]["maxLength"] == 160
    assert schema["PaymentRequestCreate"]["properties"]["note"]["maxLength"] == 500
    assert schema["DisputeCreate"]["properties"]["reason"]["maxLength"] == 1000
    assert schema["DisputeResolve"]["properties"]["resolution_note"]["maxLength"] == 1000
    assert schema["ReceiptShareReviewDispute"]["properties"]["reason"]["maxLength"] == 1000


def test_ci_runs_format_and_security_audit_gates():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "make format-check" in workflow
    assert "make security-audit" in workflow


def test_deploy_syncs_splitik_llm_env_checked_by_smoke_gate():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "SPLITIK_LLM_BASE_URL_SECRET" in workflow
    assert "secrets.SPLITIK_LLM_BASE_URL || secrets.OCR_LLM_URL" in workflow
    assert "SPLITIK_LLM_API_KEY_SECRET" in workflow
    assert "secrets.SPLITIK_LLM_API_KEY || secrets.OCR_LLM_AUTH_TOKEN" in workflow
    assert "SPLITIK_PRIMARY_MODEL_SECRET" in workflow
    assert "secrets.SPLITIK_PRIMARY_MODEL || secrets.OCR_LLM_MODEL" in workflow
    assert "SPLITIK_FAST_CHAT_MODEL_VALUE" in workflow
    assert "deepseek-v4-flash" in workflow
    assert "SPLITIK_TEXT_MODEL_POOL_VALUE" in workflow
    assert "kimi-k2.6" in workflow
    assert "SPLITIK_VISION_MODEL_POOL_VALUE" in workflow
    assert "qwen3.7-plus" in workflow
    assert "SPLITIK_VISION_SMOKE_IMAGE_URL_SECRET" in workflow
    assert "SPLITIK_INTENT_MODEL_VALUE" in workflow
    assert (
        "SPLITIK_INTENT_TIMEOUT_SECONDS: ${{ vars.SPLITIK_INTENT_TIMEOUT_SECONDS || '12' }}"
        in workflow
    )
    assert (
        "SPLITIK_INTENT_TIMEOUT_SECONDS_VALUE: ${{ vars.SPLITIK_INTENT_TIMEOUT_SECONDS || '12' }}"
        in workflow
    )
    assert ".splitik.env.incoming" in workflow
    assert "while IFS='=' read -r KEY VALUE" in workflow


def test_requirements_are_pinned_for_reproducible_installs():
    requirements = (PROJECT_ROOT / "requirements.txt").read_text().splitlines()
    package_lines = [
        line.strip() for line in requirements if line.strip() and not line.strip().startswith("#")
    ]

    assert package_lines
    assert all("==" in line for line in package_lines)


def test_production_diagnostics_workflow_fetches_sanitized_reports():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "production-diagnostics.yml").read_text()

    assert "workflow_dispatch" in workflow
    assert "DEPLOY_SSH_KEY" in workflow
    assert "docker compose exec -T" in workflow
    assert "client_feedback_reports" in workflow
    assert "splitik_interactions" in workflow
    assert "sanitized_user_message" not in workflow
    assert "upload-artifact" in workflow
    assert "production-diagnostics" in workflow


def test_client_report_endpoint_accepts_guest_feedback(db):
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.dependency_overrides[get_db] = lambda: db
    api.include_router(client_reports_router)

    client = TestClient(api)
    response = client.post(
        "/api/client-reports",
        json={
            "kind": "manual_feedback",
            "severity": "warning",
            "screen": "profile",
            "message": "Пользователь отправил отзыв",
            "user_description": "Не понял, где добавить чек.",
            "metadata": {"screen_label": "Профиль", "Authorization": "Bearer secret"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "new"
    assert body["friendly_message"] == "Спасибо. Мы получили сообщение и посмотрим его."
    stored = db.client_feedback_reports.find_one({"id": body["id"]})
    assert stored["actor_user_id"] is None
    assert "Bearer secret" not in str(stored)


def test_client_report_endpoint_links_authenticated_actor(db):
    access_token, _ = tokens.create_access_token(USER_A)
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.dependency_overrides[get_db] = lambda: db
    api.include_router(client_reports_router)

    client = TestClient(api)
    response = client.post(
        "/api/client-reports",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "kind": "automatic_error",
            "severity": "error",
            "screen": "events",
            "message": "Не удалось синхронизировать данные.",
            "request_id": "req-456",
            "client_trace_id": "trace-456",
            "metadata": {"api_status": 500, "api_path": "/api/events"},
        },
    )

    assert response.status_code == 201
    stored = db.client_feedback_reports.find_one({"id": response.json()["id"]})
    assert stored["actor_user_id"] == USER_A
    assert stored["request_id"] == "req-456"


def test_settlement_preview_endpoint_is_read_only_for_closed_event(db):
    access_token, _ = tokens.create_access_token(USER_A)
    seed_event(db)
    db.event_memberships.insert_one(
        {
            "id": "aaaaaaaa-0000-0000-0000-000000000003",
            "event_id": EVENT_ID,
            "user_id": USER_C,
            "role": "member",
            "status": "active",
            "joined_at": datetime(2026, 1, 1, tzinfo=UTC),
            "removed_at": None,
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    first = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="A paid for B",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="AB",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    second = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_B,
            title="B paid for C",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="BC",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_B,
    )
    confirm_receipt_for_all(db, first["id"], USER_A)
    confirm_receipt_for_all(db, second["id"], USER_B)
    db.events.update_one({"id": EVENT_ID}, {"$set": {"is_closed": True}})

    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.dependency_overrides[get_db] = lambda: db
    api.include_router(events_router)
    client = TestClient(api)

    response = client.get(
        f"/api/events/{EVENT_ID}/settlement-preview",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == EVENT_ID
    assert body["source_participant_ids"] == [USER_A, USER_B, USER_C]
    assert body["net_positions"] == [
        {"user_id": USER_C, "direction": "owes", "amount_kopecks": 500},
        {"user_id": USER_A, "direction": "receives", "amount_kopecks": 500},
    ]
    assert body["recommended_transfers"] == [
        {"debtor_id": USER_C, "creditor_id": USER_A, "amount_kopecks": 500}
    ]
    assert set(body["recommended_transfers"][0]) == {"debtor_id", "creditor_id", "amount_kopecks"}


def test_settlement_plan_endpoints_create_list_get_approve_and_reject(db):
    access_token, _ = tokens.create_access_token(USER_A)
    create_cycle_source(db)
    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.dependency_overrides[get_db] = lambda: db
    api.include_router(events_router)
    client = TestClient(api)

    missing_key = client.post(
        f"/api/events/{EVENT_ID}/settlement-plans",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert missing_key.status_code == 422

    created_response = client.post(
        f"/api/events/{EVENT_ID}/settlement-plans",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Idempotency-Key": "settlement-plan-api-1",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["status"] == "pending"
    assert created["algorithm_version"] == "greedy-net-v1"
    assert created["required_approver_ids"] == [USER_A, USER_B, USER_C]
    assert created["approvals"] == []
    assert "snapshot_hash" not in created
    assert "canonical_snapshot" not in created

    list_response = client.get(
        f"/api/events/{EVENT_ID}/settlement-plans?limit=1&offset=0",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == created["id"]

    get_response = client.get(
        f"/api/settlement-plans/{created['id']}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]

    approved_response = client.post(
        f"/api/settlement-plans/{created['id']}/approve",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert approved_response.status_code == 200
    assert approved_response.json()["approvals"] == [
        {"user_id": USER_A, "approved_at": approved_response.json()["approvals"][0]["approved_at"]}
    ]

    rejected_response = client.post(
        f"/api/settlement-plans/{created['id']}/reject",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"reason": "Changed my mind"},
    )
    assert rejected_response.status_code == 200
    assert rejected_response.json()["status"] == "rejected"
    assert rejected_response.json()["rejected_by"] == USER_A
    assert rejected_response.json()["rejection_reason"] == "Changed my mind"

    too_long_reason = client.post(
        f"/api/settlement-plans/{created['id']}/reject",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"reason": "x" * 501},
    )
    assert too_long_reason.status_code == 422


def test_settlement_plan_execute_endpoint_requires_key_and_materializes_requests(db):
    import importlib

    settlements = importlib.import_module("app.services.settlements")
    access_token, _ = tokens.create_access_token(USER_A)
    create_cycle_source(db)
    plan = settlements.create_settlement_plan(
        db, EVENT_ID, USER_A, idempotency_key="settlement-plan-api-execute"
    )
    approved = plan
    for user_id in plan["required_approver_ids"]:
        approved = settlements.approve_settlement_plan(db, plan["id"], user_id)

    api = FastAPI(dependencies=[Depends(require_auth_token)])
    api.dependency_overrides[get_db] = lambda: db
    api.include_router(events_router)
    client = TestClient(api)

    missing_key = client.post(
        f"/api/settlement-plans/{approved['id']}/execute",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert missing_key.status_code == 422

    executed_response = client.post(
        f"/api/settlement-plans/{approved['id']}/execute",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Idempotency-Key": "settlement-execute-api-1",
        },
    )

    assert executed_response.status_code == 200
    executed = executed_response.json()
    assert executed["status"] == "executing"
    assert executed["edges"][0]["status"] == "requested"
    assert executed["edges"][0]["payment_request_id"]
    assert db.payment_requests.count_documents({}) == 1


def test_openapi_exposes_settlement_preview_contract():
    schema = app_main.app.openapi()
    preview = schema["components"]["schemas"]["SettlementPreview"]
    net_position = schema["components"]["schemas"]["SettlementNetPosition"]
    transfer = schema["components"]["schemas"]["SettlementTransfer"]

    assert "/api/events/{id}/settlement-preview" in schema["paths"]
    assert preview["required"] == [
        "event_id",
        "raw_debts",
        "net_positions",
        "recommended_transfers",
        "source_participant_ids",
        "original_transfer_count",
        "recommended_transfer_count",
        "original_gross_kopecks",
        "recommended_total_kopecks",
        "transfer_count_reduced",
    ]
    assert set(net_position["properties"]["direction"]["enum"]) == {"owes", "receives"}
    assert transfer["required"] == ["debtor_id", "creditor_id", "amount_kopecks"]


def test_openapi_exposes_settlement_plan_contract():
    schema = app_main.app.openapi()
    paths = schema["paths"]
    plan = schema["components"]["schemas"]["SettlementPlan"]
    edge = schema["components"]["schemas"]["SettlementPlanEdge"]
    page = schema["components"]["schemas"]["SettlementPlanPage"]
    reject = schema["components"]["schemas"]["SettlementPlanReject"]

    assert "/api/events/{id}/settlement-plans" in paths
    assert "/api/settlement-plans/{id}" in paths
    assert "/api/settlement-plans/{id}/approve" in paths
    assert "/api/settlement-plans/{id}/reject" in paths
    assert "/api/settlement-plans/{id}/execute" in paths
    assert paths["/api/events/{id}/settlement-plans"]["post"]["parameters"][1]["name"] == (
        "Idempotency-Key"
    )
    execute_parameters = paths["/api/settlement-plans/{id}/execute"]["post"]["parameters"]
    assert any(parameter["name"] == "Idempotency-Key" for parameter in execute_parameters)
    assert plan["required"] == [
        "id",
        "event_id",
        "status",
        "algorithm_version",
        "preview",
        "edges",
        "required_approver_ids",
        "approvals",
        "created_by",
        "expires_at",
        "created_at",
        "updated_at",
    ]
    assert set(plan["properties"]["status"]["enum"]) == {
        "pending",
        "approved",
        "rejected",
        "stale",
        "expired",
        "executing",
        "partially_settled",
        "completed",
    }
    assert edge["required"] == ["edge_id", "debtor_id", "creditor_id", "amount_kopecks"]
    assert page["required"] == ["items", "limit", "offset", "total"]
    assert reject["properties"]["reason"]["maxLength"] == 500


def test_openapi_exposes_targeted_invitation_inbox_contract():
    schema = app_main.app.openapi()

    list_operation = schema["paths"]["/api/invites"]["get"]
    response_schema = list_operation["responses"]["200"]["content"]["application/json"]["schema"]
    create_schema = schema["components"]["schemas"]["CreateEventInviteRequest"]
    inbox_item = schema["components"]["schemas"]["EventInvitationInboxItem"]

    assert response_schema["$ref"].endswith("/EventInvitationInboxPage")
    assert "addressee_id" in create_schema["properties"]
    assert set(inbox_item["required"]) == {
        "id",
        "token",
        "event_id",
        "event_name",
        "created_by",
        "creator_name",
        "expires_at",
        "created_at",
    }


def test_payment_requests_have_unique_sparse_settlement_edge_index(db):
    indexes.ensure_indexes(db)

    matching_indexes = [
        info
        for info in db.payment_requests.index_information().values()
        if info["key"] == [("settlement_plan_id", 1), ("settlement_edge_id", 1)]
    ]

    assert matching_indexes
    assert matching_indexes[0]["unique"] is True
    assert matching_indexes[0]["sparse"] is True


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

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import schemas
from app.dependencies import get_actor_user_id, get_db, get_s3
from app.main import configure_request_logging
from app.routers import splitik as splitik_router
from app.services import (
    receipt_ai_drafts,
    receipts,
    splitik,
    splitik_attachments,
    splitik_llm,
    splitik_tools,
)
from tests.conftest import EVENT_ID, USER_A, USER_B, USER_C, seed_event, seed_users


def _mock_llm(monkeypatch):
    calls = []

    def fake_reply(*, system_prompt, user_message, context, model_role="primary"):
        calls.append(
            {
                "system_prompt": system_prompt,
                "user_message": user_message,
                "context": context,
                "model_role": model_role,
            }
        )
        return "Сплитик: готово."

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)
    return calls


def _mock_event_draft_candidate(monkeypatch, *, name="Кофе в Серф с Пашей"):
    calls = []

    def fake_candidate(*, user_message, context):
        calls.append({"user_message": user_message, "context": context})
        return {
            "model_role": "primary",
            "model_id": "primary-model",
            "content": {
                "intent": "create_event",
                "payload": {"name": name},
                "assistant_message": (
                    f"Я подготовил черновик события **{name}**.\n\n"
                    "Проверь участников и название перед подтверждением."
                ),
            },
        }

    monkeypatch.setattr(splitik_llm, "generate_event_draft_candidate", fake_candidate)
    return calls


def _mock_plan_candidate(monkeypatch, content):
    calls = []

    def fake_candidate(*, user_message, context):
        calls.append({"user_message": user_message, "context": context})
        return {
            "model_role": "primary",
            "model_id": "planner-model",
            "content": content,
        }

    monkeypatch.setattr(splitik_llm, "generate_splitik_plan_candidate", fake_candidate)
    return calls


def _mock_intent_candidate(monkeypatch, *, intent: str, confidence: float = 0.9):
    calls = []

    def fake_candidate(*, user_message, context):
        calls.append({"user_message": user_message, "context": context})
        return {
            "model_role": "primary",
            "model_id": "primary-model",
            "content": {
                "intent": intent,
                "confidence": confidence,
                "reason": "test",
            },
        }

    monkeypatch.setattr(splitik_llm, "generate_splitik_intent_candidate", fake_candidate)
    return calls


def test_explicit_event_command_creates_draft_from_llm_plan(db, monkeypatch):
    seed_users(db)
    intent_calls = _mock_intent_candidate(monkeypatch, intent="mutation")
    planner_calls = _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Подготовил черновик события.",
            "actions": [{"type": "create_event_draft", "payload": {"name": "Такси до дома"}}],
        },
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(message="Создай событие Такси до дома"),
        USER_A,
    )

    assert response["intent"] == "draft"
    assert len(response["drafts"]) == 1
    assert response["drafts"][0]["type"] == "create_event"
    assert response["drafts"][0]["payload"]["name"] == "Такси до дома"
    assert intent_calls[0]["user_message"] == "Создай событие Такси до дома"
    assert planner_calls[0]["user_message"] == "Создай событие Такси до дома"


def test_planner_context_uses_already_loaded_session_messages(db, monkeypatch):
    session = {
        "id": "session-1",
        "messages": [{"id": str(index), "user_message": f"message {index}"} for index in range(8)],
    }

    def fail_storage_read(**_kwargs):
        pytest.fail("planner context must use the session already loaded by the request")

    monkeypatch.setattr(splitik_tools, "read_recent_session_messages", fail_storage_read)

    context = splitik._planner_context(
        db,
        payload=schemas.SplitikMessageRequest(message="Создай событие"),
        actor_user_id=USER_A,
        session_id=session["id"],
        session=session,
    )

    assert context["recent_messages"] == session["messages"][-6:]


def test_splitik_router_replays_a_retried_message_without_duplicate_draft(db, monkeypatch):
    seed_users(db)
    _mock_intent_candidate(monkeypatch, intent="mutation")
    _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Подготовил черновик события.",
            "actions": [{"type": "create_event_draft", "payload": {"name": "Такси до дома"}}],
        },
    )
    api = FastAPI()
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_actor_user_id] = lambda: USER_A
    api.include_router(splitik_router.router)
    client = TestClient(api)

    headers = {"Idempotency-Key": "splitik-retry-1"}
    payload = {"mode": "general", "message": "Создай событие Такси до дома"}
    first = client.post("/api/splitik/messages", headers=headers, json=payload)
    second = client.post("/api/splitik/messages", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["message_id"] == first.json()["message_id"]
    assert db.splitik_drafts.count_documents({}) == 1


class _FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _set_llm_env(monkeypatch):
    monkeypatch.setenv("SPLITIK_LLM_BASE_URL", "https://ai.example/v1")
    monkeypatch.setenv("SPLITIK_LLM_API_KEY", "test-key")
    monkeypatch.setenv("SPLITIK_PRIMARY_MODEL", "primary-model")
    monkeypatch.delenv("SPLITIK_FAST_CHAT_MODEL", raising=False)
    monkeypatch.delenv("SPLITIK_INTENT_MODEL", raising=False)
    monkeypatch.setenv("SPLITIK_VERIFICATION_MODEL", "verification-model")
    monkeypatch.setenv("SPLITIK_ESCALATION_MODEL", "escalation-model")


def _receipt_ai_candidate(model_role, payload=None, warnings=None):
    draft_payload = payload or {
        "payer_id": USER_A,
        "title": "Кофе",
        "category": "Кафе",
        "total_amount_kopecks": 1000,
        "items": [
            {
                "name": "Капучино",
                "cost_kopecks": 1000,
                "split_mode": "custom",
                "share_items": [
                    {"user_id": USER_A, "share_value": "0.5"},
                    {"user_id": USER_B, "share_value": "0.5"},
                ],
            }
        ],
        "discount_amount_kopecks": 0,
        "service_fee_amount_kopecks": 0,
        "delivery_fee_amount_kopecks": 0,
        "tip_amount_kopecks": 0,
        "rounding_adjustment_kopecks": 0,
        "fiscal_total_amount_kopecks": None,
        "vat_amount_kopecks": None,
    }
    return {
        "model_role": model_role,
        "model_id": f"{model_role}-model",
        "content": {"payload": draft_payload, "warnings": warnings or []},
    }


def test_splitik_event_context_requires_membership(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    with pytest.raises(HTTPException) as exc:
        splitik.send_splitik_message(
            db,
            schemas.SplitikMessageRequest(
                mode="event",
                message="Что по балансу?",
                entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
            ),
            USER_C,
        )

    assert exc.value.status_code == 403


def test_receipt_ai_draft_uses_primary_and_verification_without_creating_receipt(db, monkeypatch):
    seed_event(db)
    calls = []

    def fake_candidate(*, model_role, system_prompt, user_message, context):
        calls.append({"role": model_role, "context": context, "message": user_message})
        return _receipt_ai_candidate(model_role)

    monkeypatch.setattr(splitik_llm, "generate_receipt_draft_candidate", fake_candidate)

    draft = receipt_ai_drafts.create_receipt_ai_draft(
        db,
        EVENT_ID,
        schemas.ReceiptAIDraftRequest(source_text="Капучино 10.00", payer_id=USER_A),
        USER_A,
    )

    assert [call["role"] for call in calls] == ["primary", "verification"]
    assert draft["model_status"] == "matched"
    assert draft["needs_human_review"] is True
    assert draft["draft_payload"]["total_amount_kopecks"] == 1000
    assert draft["primary_result"]["payload"]["items"][0]["name"] == "Капучино"
    assert db.receipt_ai_drafts.count_documents({"event_id": EVENT_ID}) == 1
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0


def test_receipt_ai_draft_escalates_when_models_disagree(db, monkeypatch):
    seed_event(db)
    calls = []
    verification_payload = _receipt_ai_candidate("verification")["content"]["payload"]
    verification_payload = {**verification_payload, "total_amount_kopecks": 1200}

    def fake_candidate(*, model_role, system_prompt, user_message, context):
        calls.append(model_role)
        if model_role == "verification":
            return _receipt_ai_candidate(model_role, verification_payload)
        if model_role == "escalation":
            return _receipt_ai_candidate(
                model_role, warnings=["Primary and verification disagreed."]
            )
        return _receipt_ai_candidate(model_role)

    monkeypatch.setattr(splitik_llm, "generate_receipt_draft_candidate", fake_candidate)

    draft = receipt_ai_drafts.create_receipt_ai_draft(
        db,
        EVENT_ID,
        schemas.ReceiptAIDraftRequest(source_text="Капучино спорная сумма", payer_id=USER_A),
        USER_A,
    )

    assert calls == ["primary", "verification", "escalation"]
    assert draft["model_status"] == "escalated"
    assert "total_amount_kopecks" in draft["disagreements"]
    assert draft["escalation_result"]["warnings"] == ["Primary and verification disagreed."]
    assert draft["draft_payload"]["total_amount_kopecks"] == 1000
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0


def test_receipt_ai_draft_requires_event_membership(db, monkeypatch):
    seed_event(db)
    monkeypatch.setattr(
        splitik_llm,
        "generate_receipt_draft_candidate",
        lambda **kwargs: _receipt_ai_candidate(kwargs["model_role"]),
    )

    with pytest.raises(HTTPException) as exc:
        receipt_ai_drafts.create_receipt_ai_draft(
            db,
            EVENT_ID,
            schemas.ReceiptAIDraftRequest(source_text="Капучино 10.00", payer_id=USER_A),
            USER_C,
        )

    assert exc.value.status_code == 403
    assert db.receipt_ai_drafts.count_documents({}) == 0


def test_splitik_llm_uses_runtime_primary_model(monkeypatch):
    _set_llm_env(monkeypatch)
    requests = []

    def fake_post(url, headers, json, timeout):
        requests.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse(body={"choices": [{"message": {"content": "Сплитик: готово."}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    reply = splitik_llm.generate_splitik_reply(
        system_prompt="system",
        user_message="hello",
        context={"allowed": True},
    )

    assert reply == "Сплитик: готово."
    assert requests[0]["url"] == "https://ai.example/v1/chat/completions"
    assert requests[0]["json"]["model"] == "primary-model"
    assert requests[0]["timeout"] == 12


def test_splitik_llm_fast_chat_defaults_to_deepseek_flash(monkeypatch):
    _set_llm_env(monkeypatch)
    requests = []

    def fake_post(url, headers, json, timeout):
        requests.append({"json": json, "timeout": timeout})
        return _FakeResponse(body={"choices": [{"message": {"content": "Привет!"}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    reply = splitik_llm.generate_splitik_reply(
        system_prompt="system",
        user_message="привет",
        context={"allowed": True},
        model_role="fast_chat",
    )

    assert reply == "Привет!"
    assert requests[0]["json"]["model"] == "deepseek-v4-flash"
    assert requests[0]["timeout"] == 12


def test_splitik_llm_timeout_can_be_overridden(monkeypatch):
    _set_llm_env(monkeypatch)
    monkeypatch.setenv("SPLITIK_LLM_TIMEOUT_SECONDS", "35")
    requests = []

    def fake_post(url, headers, json, timeout):
        requests.append({"timeout": timeout})
        return _FakeResponse(body={"choices": [{"message": {"content": "Сплитик: готово."}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    splitik_llm.generate_splitik_reply(
        system_prompt="system",
        user_message="hello",
        context={"allowed": True},
    )

    assert requests[0]["timeout"] == 35


def test_splitik_intent_router_uses_small_runtime_model(monkeypatch):
    _set_llm_env(monkeypatch)
    monkeypatch.setenv("SPLITIK_INTENT_MODEL", "deepseek-v4-flash")
    requests = []

    def fake_post(url, headers, json, timeout):
        requests.append(json)
        return _FakeResponse(
            body={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"intent":"explain","confidence":0.91,"reason":"user asks why"}'
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    candidate = splitik_llm.generate_splitik_intent_candidate(
        user_message="Почему я должен?",
        context={"mode": "event"},
    )

    assert candidate["model_role"] == "intent"
    assert candidate["model_id"] == "deepseek-v4-flash"
    assert candidate["content"]["intent"] == "explain"
    assert requests[0]["model"] == "deepseek-v4-flash"


def test_splitik_chat_supports_legacy_primary_model_without_receipt_models(monkeypatch):
    monkeypatch.setenv("SPLITIK_LLM_BASE_URL", "https://ai.example/v1")
    monkeypatch.setenv("SPLITIK_LLM_API_KEY", "test-key")
    monkeypatch.setenv("SPLITIK_LLM_MODEL", "legacy-primary")
    monkeypatch.delenv("SPLITIK_PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("SPLITIK_VERIFICATION_MODEL", raising=False)
    monkeypatch.delenv("SPLITIK_ESCALATION_MODEL", raising=False)
    requests = []

    def fake_post(url, headers, json, timeout):
        requests.append(json)
        return _FakeResponse(body={"choices": [{"message": {"content": "Сплитик: legacy."}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    assert (
        splitik_llm.generate_splitik_reply(
            system_prompt="system",
            user_message="hello",
            context={"allowed": True},
        )
        == "Сплитик: legacy."
    )
    assert requests[0]["model"] == "legacy-primary"

    with pytest.raises(HTTPException) as exc:
        splitik_llm.generate_receipt_draft_candidate(
            model_role="verification",
            system_prompt="system",
            user_message="receipt",
            context={},
        )
    assert exc.value.status_code == 503


def test_splitik_startup_validation_accepts_available_runtime_models(monkeypatch):
    _set_llm_env(monkeypatch)
    monkeypatch.setenv("SPLITIK_INTENT_MODEL", "deepseek-v4-flash")
    requests = []

    def fake_get(url, headers, timeout):
        requests.append({"url": url, "headers": headers, "timeout": timeout})
        return _FakeResponse(
            body={
                "data": [
                    {"id": "primary-model"},
                    {"id": "deepseek-v4-flash"},
                    {"id": "verification-model"},
                    {"id": "escalation-model"},
                    {"id": "minimax-m3"},
                ]
            }
        )

    monkeypatch.setattr(splitik_llm.httpx, "get", fake_get)

    splitik_llm.validate_configured_models_available()

    assert requests[0]["url"] == "https://ai.example/v1/models"


def test_splitik_startup_validation_rejects_unavailable_runtime_model(monkeypatch):
    _set_llm_env(monkeypatch)
    monkeypatch.setenv("SPLITIK_INTENT_MODEL", "deepseek-v4-flash")

    def fake_get(url, headers, timeout):
        return _FakeResponse(body={"data": [{"id": "primary-model"}, {"id": "verification-model"}]})

    monkeypatch.setattr(splitik_llm.httpx, "get", fake_get)

    with pytest.raises(RuntimeError):
        splitik_llm.validate_configured_models_available()


def test_splitik_llm_is_mocked_and_receives_bounded_event_context(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_event(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Почему я должен?",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["assistant_message"] == "Сплитик: готово."
    assert response["context_chips"][0]["value"] == "Trip"
    assert "read:balance_explanation" in response["capabilities"]
    assert calls[0]["context"]["event"]["id"] == EVENT_ID
    assert {item["membership"]["user_id"] for item in calls[0]["context"]["participants"]} == {
        USER_A,
        USER_B,
    }


def test_splitik_explanation_intent_skips_json_planner(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    intent_calls = _mock_intent_candidate(monkeypatch, intent="explain")
    seed_event(db)

    def fail_planner(*, user_message, context):
        raise AssertionError("explanation requests should not call the JSON planner")

    monkeypatch.setattr(splitik_llm, "generate_splitik_plan_candidate", fail_planner)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Почему я должен?",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["intent"] == "explain"
    assert response["assistant_message"] == "Сплитик: готово."
    assert response["drafts"] == []
    assert len(intent_calls) == 1
    assert calls[0]["context"]["event"]["id"] == EVENT_ID


def test_splitik_refuses_homework_and_logs_interaction(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_users(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Реши домашку по алгебре"),
        USER_A,
    )

    assert calls == []
    assert response["intent"] == "refusal"
    assert response["guardrail_decision"]["allowed"] is False
    assert response["guardrail_decision"]["reason"] == "out_of_scope_homework"
    assert "SplitApp" in response["assistant_message"]
    log = db.splitik_interactions.find_one({"actor_user_id": USER_A})
    assert log is not None
    assert log["intent"] == "refusal"
    assert log["guardrail_decision"]["reason"] == "out_of_scope_homework"
    assert "алгебре" in log["sanitized_user_message"]


def test_splitik_logs_allowed_message_without_tokens(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_users(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Сколько я должен? token=secret-token Authorization: Bearer abc",
        ),
        USER_A,
    )

    assert response["guardrail_decision"]["allowed"] is True
    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert log is not None
    assert "secret-token" not in log["sanitized_user_message"]
    assert "Bearer abc" not in log["sanitized_user_message"]


def test_splitik_logs_request_context_summary_and_request_id(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Что по этому событию?",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
        request_id="req-splitik-123",
    )

    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert log is not None
    assert log["request_id"] == "req-splitik-123"
    assert log["status"] == "success"
    assert log["stage"] == "completed"
    assert log["latency_ms"] >= 0
    assert log["context_summary"]["mode"] == "event"
    assert log["context_summary"]["entry_point_type"] == "event"
    assert log["context_summary"]["event_id"] == EVENT_ID
    assert log["context_summary"]["context_counts"]["receipts"] == 0
    assert log["model_ids"] == ["fast_chat"]
    assert log["error"] is None


def test_splitik_logs_llm_error_for_later_debugging(db, monkeypatch):
    seed_users(db)

    def fake_reply(*, system_prompt, user_message, context, model_role="primary"):
        raise HTTPException(status_code=502, detail="Splitik LLM provider returned an error.")

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)

    with pytest.raises(HTTPException) as exc:
        splitik.send_splitik_message(
            db,
            schemas.SplitikMessageRequest(mode="general", message="Сколько я должен?"),
            USER_A,
            request_id="req-error-456",
        )

    assert exc.value.status_code == 502
    log = db.splitik_interactions.find_one({"request_id": "req-error-456"})
    assert log is not None
    assert log["status"] == "error"
    assert log["stage"] == "llm.generate_reply"
    assert log["intent"] == "error"
    assert log["error"]["type"] == "HTTPException"
    assert log["error"]["http_status"] == 502
    assert log["error"]["message"] == "Splitik LLM provider returned an error."
    assert log["latency_ms"] >= 0
    assert log["context_summary"]["mode"] == "general"
    assert "Authorization" not in str(log)
    assert "Bearer" not in str(log)


def test_splitik_message_endpoint_passes_request_id_to_interaction_log(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_users(db)
    api = FastAPI()
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_actor_user_id] = lambda: USER_A
    api.include_router(splitik_router.router)
    configure_request_logging(api)
    client = TestClient(api)

    response = client.post(
        "/api/splitik/messages",
        headers={"X-Request-ID": "req-router-789"},
        json={"mode": "general", "message": "Что у меня по событиям?"},
    )

    assert response.status_code == 200
    log = db.splitik_interactions.find_one({"message_id": response.json()["message_id"]})
    assert log is not None
    assert log["request_id"] == "req-router-789"


def test_splitik_blocks_llm_claiming_direct_state_change(db, monkeypatch):
    seed_users(db)

    def fake_reply(*, system_prompt, user_message, context, model_role="primary"):
        return "Готово, я удалил событие и изменил баланс."

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Что по событиям?"),
        USER_A,
    )

    assert response["intent"] == "guardrail"
    assert response["guardrail_decision"]["allowed"] is False
    assert response["guardrail_decision"]["reason"] == "unsafe_model_state_change_claim"
    assert "не изменил данные" in response["assistant_message"]
    assert "удалил событие" not in response["assistant_message"]
    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert log is not None
    assert log["intent"] == "guardrail"
    assert log["guardrail_decision"]["reason"] == "unsafe_model_state_change_claim"


def test_splitik_blocks_llm_private_friend_spending_leak(db, monkeypatch):
    seed_users(db)

    def fake_reply(*, system_prompt, user_message, context, model_role="primary"):
        return "Bob тратит деньги на бары и такси вне ваших общих событий."

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Расскажи что-нибудь про друзей"),
        USER_A,
    )

    assert response["intent"] == "guardrail"
    assert response["guardrail_decision"]["allowed"] is False
    assert response["guardrail_decision"]["reason"] == "unsafe_model_private_spending_claim"
    assert "не могу раскрывать личные траты" in response["assistant_message"]
    assert "бары" not in response["assistant_message"]
    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert log is not None
    assert log["intent"] == "guardrail"
    assert log["guardrail_decision"]["reason"] == "unsafe_model_private_spending_claim"


def test_splitik_draft_does_not_change_state_until_commit(db, monkeypatch):
    _mock_event_draft_candidate(monkeypatch, name="Ужин в Duo")
    seed_users(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Создай событие: Ужин в Duo",
        ),
        USER_A,
    )

    assert len(response["drafts"]) == 1
    assert db.events.count_documents({"name": "Ужин в Duo"}) == 0

    committed = splitik.commit_splitik_draft(db, response["drafts"][0]["id"], USER_A)

    assert committed["draft"]["status"] == "committed"
    assert committed["resource"]["name"] == "Ужин в Duo"
    assert db.events.count_documents({"name": "Ужин в Duo"}) == 1


def test_splitik_event_draft_uses_llm_candidate_instead_of_scripted_reply(db, monkeypatch):
    seed_users(db)
    candidate_calls = _mock_event_draft_candidate(monkeypatch, name="Кофе в Серф с Пашей")

    def fake_reply(*, system_prompt, user_message, context):
        raise AssertionError("event draft should use the LLM event candidate response")

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Создай событие. Мы с пашей ивановым ходили пить кофе в серф",
        ),
        USER_A,
        request_id="req-draft-no-llm",
    )

    assert candidate_calls[0]["user_message"] == (
        "Создай событие. Мы с пашей ивановым ходили пить кофе в серф"
    )
    assert response["intent"] == "draft"
    assert len(response["drafts"]) == 1
    assert response["drafts"][0]["type"] == "create_event"
    assert response["drafts"][0]["payload"]["name"] == "Кофе в Серф с Пашей"
    assert response["drafts"][0]["source"] == "llm"
    assert response["assistant_message"] == (
        "Я подготовил черновик события **Кофе в Серф с Пашей**.\n\n"
        "Проверь участников и название перед подтверждением."
    )
    assert db.events.count_documents({}) == 0

    log = db.splitik_interactions.find_one({"request_id": "req-draft-no-llm"})
    assert log is not None
    assert log["status"] == "success"
    assert log["intent"] == "draft"
    assert log["model_ids"] == ["primary-model"]
    assert log["error"] is None


def test_splitik_event_draft_uses_recent_context_for_followup_creation(db, monkeypatch):
    seed_users(db)
    _mock_llm(monkeypatch)

    first = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="привет. мы с пашей ходили пить кофе в серф",
        ),
        USER_A,
    )

    candidate_calls = []

    def fake_candidate(*, user_message, context):
        candidate_calls.append({"user_message": user_message, "context": context})
        return {
            "model_role": "primary",
            "model_id": "primary-model",
            "content": {
                "intent": "create_event",
                "payload": {"name": "Кофе в Серф с Пашей"},
                "assistant_message": (
                    "Подготовил черновик события **Кофе в Серф с Пашей**.\n\n"
                    "Чеки не добавляю. Проверь название и подтверди создание."
                ),
            },
        }

    monkeypatch.setattr(splitik_llm, "generate_event_draft_candidate", fake_candidate)

    created = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            session_id=first["session_id"],
            mode="general",
            message="Ну ты просто создай событие. Не добавляй туда чеков",
        ),
        USER_A,
    )

    assert candidate_calls[0]["context"]["recent_messages"][0]["user_message"] == (
        "привет. мы с пашей ходили пить кофе в серф"
    )
    assert created["intent"] == "draft"
    assert created["drafts"][0]["payload"]["name"] == "Кофе в Серф с Пашей"
    assert "Не добавляй туда чеков" not in created["drafts"][0]["payload"]["name"]
    assert "Чеки не добавляю" in created["assistant_message"]


def test_splitik_rejects_instruction_text_as_event_name(db, monkeypatch):
    seed_users(db)
    _mock_llm(monkeypatch)

    def fake_candidate(*, user_message, context):
        return {
            "model_role": "primary",
            "model_id": "primary-model",
            "content": {
                "intent": "create_event",
                "payload": {"name": "Не добавляй туда чеков"},
                "assistant_message": "Создал черновик события **Не добавляй туда чеков**.",
            },
        }

    monkeypatch.setattr(splitik_llm, "generate_event_draft_candidate", fake_candidate)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Ну ты просто создай событие. Не добавляй туда чеков",
        ),
        USER_A,
    )

    assert response["intent"] == "chat"
    assert response["drafts"] == []
    assert db.splitik_drafts.count_documents({}) == 0


def test_splitik_planner_creates_multiple_event_drafts(db, monkeypatch):
    seed_users(db)
    _mock_llm(monkeypatch)
    intent_calls = _mock_intent_candidate(monkeypatch, intent="mutation")
    _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Подготовил два черновика событий.",
            "actions": [
                {"type": "create_event_draft", "payload": {"name": "Кофе в Серф"}},
                {"type": "create_event_draft", "payload": {"name": "Ужин в Duo"}},
            ],
        },
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Создай два события: кофе в Серф и ужин в Duo",
        ),
        USER_A,
    )

    assert response["intent"] == "draft"
    assert [draft["payload"]["name"] for draft in response["drafts"]] == [
        "Кофе в Серф",
        "Ужин в Duo",
    ]
    assert response["assistant_message"] == "Подготовил два черновика событий."
    assert db.events.count_documents({}) == 0
    assert len(intent_calls) == 1


def test_splitik_planner_limits_drafts_per_request_before_writes(db, monkeypatch):
    monkeypatch.setenv("SPLITIK_MAX_DRAFTS_PER_REQUEST", "1")
    seed_users(db)
    _mock_llm(monkeypatch)
    _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Подготовил два черновика событий.",
            "actions": [
                {"type": "create_event_draft", "payload": {"name": "Кофе в Серф"}},
                {"type": "create_event_draft", "payload": {"name": "Ужин в Duo"}},
            ],
        },
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Создай два события: кофе в Серф и ужин в Duo",
        ),
        USER_A,
    )

    assert response["intent"] == "guardrail"
    assert response["drafts"] == []
    assert response["guardrail_decision"]["reason"] == "splitik_draft_request_limit"
    assert db.splitik_drafts.count_documents({}) == 0


def test_splitik_limits_pending_drafts_per_user(db, monkeypatch):
    monkeypatch.setenv("SPLITIK_PENDING_DRAFT_LIMIT", "1")
    seed_users(db)
    _mock_llm(monkeypatch)
    splitik_tools.create_event_draft(
        db,
        actor_user_id=USER_A,
        session_id="aaaaaaaa-1111-1111-1111-111111111111",
        payload={"name": "Старый черновик"},
        source="planner",
    )
    _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Подготовил черновик события.",
            "actions": [{"type": "create_event_draft", "payload": {"name": "Новый черновик"}}],
        },
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Создай событие"),
        USER_A,
    )

    assert response["intent"] == "guardrail"
    assert response["drafts"] == []
    assert response["guardrail_decision"]["reason"] == "splitik_pending_draft_limit"
    assert db.splitik_drafts.count_documents({"owner_user_id": USER_A}) == 1


def test_splitik_vision_receives_all_attachment_metadata(db, fake_s3, monkeypatch):
    _mock_llm(monkeypatch)
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    seed_event(db)
    first = splitik_attachments.create_attachment(
        db,
        fake_s3,
        actor_user_id=USER_A,
        filename="receipt-1.jpg",
        content_type="image/jpeg",
        content=b"\xff\xd8\xfffirst",
    )
    second = splitik_attachments.create_attachment(
        db,
        fake_s3,
        actor_user_id=USER_A,
        filename="receipt-2.jpg",
        content_type="image/jpeg",
        content=b"\xff\xd8\xffsecond",
    )
    vision_calls = []

    def fake_image_candidate(*, model_role, attachment_metadata, image_urls, user_message, context):
        vision_calls.append(
            {
                "model_role": model_role,
                "attachment_metadata": attachment_metadata,
                "image_urls": image_urls,
                "user_message": user_message,
                "context": context,
            }
        )
        return _receipt_ai_candidate(model_role)

    monkeypatch.setattr(splitik_llm, "generate_receipt_image_candidate", fake_image_candidate)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Создай черновики по двум фото",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
            attachment_ids=[first["id"], second["id"]],
        ),
        USER_A,
        s3=fake_s3,
    )

    attachment_ids = [attachment["id"] for attachment in vision_calls[0]["attachment_metadata"]]
    assert attachment_ids == [first["id"], second["id"]]
    assert "key" not in str(vision_calls[0]["attachment_metadata"])
    assert len(vision_calls[0]["image_urls"]) == 2
    assert response["intent"] == "draft"
    assert db.splitik_drafts.count_documents({}) == 1


def test_splitik_rejects_too_many_attachments_per_message(db, monkeypatch):
    monkeypatch.setenv("SPLITIK_ATTACHMENTS_PER_MESSAGE", "3")
    seed_users(db)
    _mock_llm(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        splitik.send_splitik_message(
            db,
            schemas.SplitikMessageRequest(
                mode="general",
                message="Разбери фото чеков",
                attachment_ids=[
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4",
                ],
            ),
            USER_A,
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "Too many Splitik attachments in one message."
    assert db.splitik_sessions.count_documents({}) == 0
    assert db.splitik_drafts.count_documents({}) == 0
    assert db.splitik_interactions.find_one({"error.type": "HTTPException"}) is not None


def test_splitik_planner_creates_receipt_draft_from_structured_json(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)
    receipt_payload = _receipt_ai_candidate("primary")["content"]["payload"]
    _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Подготовил черновик чека.",
            "actions": [
                {
                    "type": "create_receipt_draft",
                    "event_id": EVENT_ID,
                    "payload": receipt_payload,
                    "questions": [],
                }
            ],
        },
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: капучино 10 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["intent"] == "draft"
    assert len(response["drafts"]) == 1
    assert response["drafts"][0]["type"] == "create_receipt"
    assert response["drafts"][0]["payload"]["items"][0]["name"] == "Капучино"
    assert response["drafts"][0]["model_metadata"]["model_id"] == "planner-model"
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0


def test_splitik_planner_rejects_forbidden_action_without_writes(db, monkeypatch):
    seed_event(db)
    _mock_llm(monkeypatch)
    _mock_plan_candidate(
        monkeypatch,
        {
            "intent": "create_drafts",
            "assistant_message": "Я удалил событие.",
            "actions": [
                {
                    "type": "delete_event",
                    "event_id": EVENT_ID,
                    "$where": "this.creator_id != null",
                }
            ],
        },
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Удали событие",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["intent"] == "guardrail"
    assert response["drafts"] == []
    assert response["guardrail_decision"]["reason"] == "forbidden_operation"
    assert db.splitik_drafts.count_documents({}) == 0


def test_splitik_receipt_draft_update_is_scoped_to_current_event(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)
    second_event_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.events.insert_one(
        {
            "id": second_event_id,
            "creator_id": USER_A,
            "name": "Dinner",
            "is_closed": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    db.event_memberships.insert_many(
        [
            {
                "id": "dddddddd-0000-0000-0000-000000000001",
                "event_id": second_event_id,
                "user_id": USER_A,
                "role": "creator",
                "status": "active",
                "joined_at": now,
                "removed_at": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "dddddddd-0000-0000-0000-000000000002",
                "event_id": second_event_id,
                "user_id": USER_B,
                "role": "member",
                "status": "active",
                "joined_at": now,
                "removed_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    created = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )
    first_draft_id = created["drafts"][0]["id"]

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            session_id=created["session_id"],
            mode="event",
            message="Поменяй сумму на 1500 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=second_event_id),
        ),
        USER_A,
    )

    stored = db.splitik_drafts.find_one({"id": first_draft_id})
    assert stored["payload"]["total_amount_kopecks"] == 120000
    assert response["drafts"] == []


def test_splitik_creates_receipt_draft_from_event_text_without_changing_money(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["intent"] == "draft"
    assert len(response["drafts"]) == 1
    draft = response["drafts"][0]
    assert draft["type"] == "create_receipt"
    assert draft["status"] == "pending"
    assert draft["event_id"] == EVENT_ID
    assert draft["source"] == "text"
    assert draft["version"] == 1
    assert draft["payload"]["payer_id"] == USER_A
    assert draft["payload"]["total_amount_kopecks"] == 120000
    assert draft["payload"]["items"][0]["cost_kopecks"] == 120000
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0


def test_splitik_receipt_draft_returns_clarifying_questions(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    question_ids = {question["id"] for question in response["questions"]}
    assert {"payer", "participants", "split_details"} <= question_ids
    assert response["drafts"][0]["questions"] == response["questions"]


def test_splitik_followup_answers_receipt_draft_questions(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    created = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )
    draft_id = created["drafts"][0]["id"]
    assert created["questions"]

    answered = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            session_id=created["session_id"],
            mode="event",
            message="Я платил, были все участники, делим поровну",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert answered["intent"] == "draft"
    assert answered["questions"] == []
    assert answered["drafts"][0]["id"] == draft_id
    assert answered["drafts"][0]["version"] == 2
    assert answered["drafts"][0]["questions"] == []
    assert answered["drafts"][0]["model_metadata"]["answered_question_ids"] == [
        "payer",
        "participants",
        "split_details",
    ]


def test_splitik_updates_receipt_draft_from_chat(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    created = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )
    draft_id = created["drafts"][0]["id"]

    updated = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            session_id=created["session_id"],
            mode="event",
            message="Поменяй сумму на 1500 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert updated["intent"] == "draft"
    assert updated["drafts"][0]["id"] == draft_id
    assert updated["drafts"][0]["version"] == 2
    assert updated["drafts"][0]["payload"]["total_amount_kopecks"] == 150000
    assert updated["drafts"][0]["payload"]["items"][0]["cost_kopecks"] == 150000
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0


def test_splitik_sends_russian_prompt_and_session_state_to_llm(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_event(db)

    created = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )
    draft_id = created["drafts"][0]["id"]

    splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            session_id=created["session_id"],
            mode="event",
            message="Что сейчас в этом черновике?",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert "Ты Сплитик" in calls[-1]["system_prompt"]
    state = calls[-1]["context"]["conversation_state"]
    assert state["session_id"] == created["session_id"]
    assert state["active_draft"]["id"] == draft_id
    assert state["active_draft"]["type"] == "create_receipt"
    assert state["recent_messages"][0]["user_message"] == "Добавь чек: кофе 1200 рублей"
    assert "splitik.get_active_draft" in calls[-1]["context"]["available_tools"]
    assert calls[-1]["context"]["tool_results"]["splitik.get_active_draft"]["id"] == draft_id
    assert calls[-1]["context"]["tool_results"]["splitik.get_recent_session_messages"]


def test_splitik_prompt_requires_markdown_and_no_emoji(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_event(db)

    splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="привет"),
        USER_A,
    )

    system_prompt = calls[-1]["system_prompt"]
    assert calls[-1]["model_role"] == "fast_chat"
    assert "Markdown" in system_prompt
    assert "emoji" in system_prompt
    assert "без emoji" in system_prompt
    assert "короткие абзацы" in system_prompt
    assert "маркированные списки" in system_prompt


def test_splitik_plain_chat_skips_intent_router(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_event(db)

    def fail_intent_router(*, user_message, context):
        raise AssertionError("plain chat should go directly to the fast chat model")

    monkeypatch.setattr(splitik_llm, "generate_splitik_intent_candidate", fail_intent_router)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="привет"),
        USER_A,
    )

    assert response["intent"] == "chat"
    assert response["assistant_message"] == "Сплитик: готово."
    assert calls[-1]["model_role"] == "fast_chat"


def test_splitik_strips_emoji_from_llm_reply(db, monkeypatch):
    def fake_reply(*, system_prompt, user_message, context, model_role="primary"):
        return "Привет! 👋\n\n- Создам черновик 🙂\n- Попрошу подтвердить"

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)
    seed_event(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="привет"),
        USER_A,
    )

    assert response["assistant_message"] == "Привет!\n\n- Создам черновик\n- Попрошу подтвердить"


def test_splitik_new_session_does_not_reuse_previous_active_draft(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_event(db)

    splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Поменяй сумму на 1500 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["drafts"] == []
    assert "active_draft" not in calls[-1]["context"]["conversation_state"]
    assert calls[-1]["context"]["tool_results"]["splitik.get_active_draft"] is None


def test_splitik_rejects_foreign_draft_commit(db, monkeypatch):
    _mock_event_draft_candidate(monkeypatch, name="Поездка")
    seed_users(db)
    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Создай событие: Поездка"),
        USER_A,
    )

    with pytest.raises(HTTPException) as exc:
        splitik.commit_splitik_draft(db, response["drafts"][0]["id"], USER_B)

    assert exc.value.status_code == 404


def test_splitik_draft_read_update_is_owner_scoped(db, monkeypatch):
    _mock_event_draft_candidate(monkeypatch, name="Поездка")
    seed_users(db)
    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Создай событие: Поездка"),
        USER_A,
    )
    draft_id = response["drafts"][0]["id"]

    draft = splitik.get_splitik_draft(db, draft_id, USER_A)
    assert draft["payload"]["name"] == "Поездка"

    updated = splitik.update_splitik_draft(
        db,
        draft_id,
        schemas.SplitikDraftUpdateRequest(payload={"name": "Поездка в Казань"}),
        USER_A,
    )
    assert updated["version"] == 2
    assert updated["payload"]["name"] == "Поездка в Казань"

    with pytest.raises(HTTPException) as read_exc:
        splitik.get_splitik_draft(db, draft_id, USER_B)
    assert read_exc.value.status_code == 404

    with pytest.raises(HTTPException) as update_exc:
        splitik.update_splitik_draft(
            db,
            draft_id,
            schemas.SplitikDraftUpdateRequest(payload={"name": "Чужая правка"}),
            USER_B,
        )
    assert update_exc.value.status_code == 404


def test_splitik_commits_receipt_draft_only_on_explicit_commit(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)
    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Добавь чек: кофе 1200 рублей",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )
    draft_id = response["drafts"][0]["id"]
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0

    committed = splitik.commit_splitik_draft(db, draft_id, USER_A)

    assert committed["draft"]["status"] == "committed"
    assert committed["resource"]["event_id"] == EVENT_ID
    assert committed["resource"]["status"] == "draft"
    assert committed["resource"]["total_amount_kopecks"] == 120000
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 1


def test_splitik_creates_receipt_draft_from_image_attachment(db, fake_s3, monkeypatch):
    _mock_llm(monkeypatch)
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    seed_event(db)
    attachment = splitik_attachments.create_attachment(
        db,
        fake_s3,
        actor_user_id=USER_A,
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"\xff\xd8\xfffake-jpeg",
    )
    image_calls = []

    def fake_image_candidate(*, model_role, attachment_metadata, image_urls, user_message, context):
        image_calls.append(
            {
                "model_role": model_role,
                "attachment_metadata": attachment_metadata,
                "image_urls": image_urls,
                "user_message": user_message,
                "context": context,
            }
        )
        return _receipt_ai_candidate(model_role)

    monkeypatch.setattr(splitik_llm, "generate_receipt_image_candidate", fake_image_candidate)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Создай черновик чека по фото",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
            attachment_ids=[attachment["id"]],
        ),
        USER_A,
        s3=fake_s3,
    )

    assert image_calls[0]["model_role"] == "vision"
    assert image_calls[0]["attachment_metadata"][0]["id"] == attachment["id"]
    assert "key" not in image_calls[0]["attachment_metadata"][0]
    assert image_calls[0]["image_urls"][0].startswith("https://signed.example/")
    assert response["intent"] == "draft"
    draft = response["drafts"][0]
    assert draft["type"] == "create_receipt"
    assert draft["source"] == "image"
    assert draft["attachment_ids"] == [attachment["id"]]
    assert draft["payload"]["items"][0]["name"] == "Капучино"
    assert {question["id"] for question in response["questions"]} == {
        "payer",
        "participants",
        "split_details",
    }
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0
    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert log is not None
    assert "attachments/" not in str(log)
    assert "test-bucket" not in str(log)


def test_splitik_routes_event_image_to_vision_receipt_draft(db, fake_s3, monkeypatch):
    _mock_llm(monkeypatch)
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    seed_event(db)
    attachment = splitik_attachments.create_attachment(
        db,
        fake_s3,
        actor_user_id=USER_A,
        filename="receipt.jpg",
        content_type="image/jpeg",
        content=b"\xff\xd8\xffreceipt-image-bytes",
    )

    def fail_intent(**_kwargs):
        raise AssertionError("an image receipt must bypass the text intent router")

    def fail_planner(**_kwargs):
        raise AssertionError("an image receipt must bypass the text planner")

    image_calls = []

    def fake_image_candidate(*, model_role, attachment_metadata, image_urls, user_message, context):
        image_calls.append(
            {
                "model_role": model_role,
                "attachment_metadata": attachment_metadata,
                "image_urls": image_urls,
                "user_message": user_message,
                "context": context,
            }
        )
        return _receipt_ai_candidate(model_role)

    monkeypatch.setattr(splitik_llm, "generate_splitik_intent_candidate", fail_intent)
    monkeypatch.setattr(splitik_llm, "generate_splitik_plan_candidate", fail_planner)
    monkeypatch.setattr(splitik_llm, "generate_receipt_image_candidate", fake_image_candidate)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Это чек за ужин",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
            attachment_ids=[attachment["id"]],
        ),
        USER_A,
        s3=fake_s3,
    )

    assert image_calls[0]["model_role"] == "vision"
    assert image_calls[0]["attachment_metadata"][0]["id"] == attachment["id"]
    assert "key" not in image_calls[0]["attachment_metadata"][0]
    assert image_calls[0]["image_urls"][0].startswith("https://signed.example/")
    assert "receipt-image-bytes" not in image_calls[0]["image_urls"][0]
    assert response["drafts"][0]["type"] == "create_receipt"
    assert response["drafts"][0]["status"] == "pending"
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0
    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert "data:image" not in str(log)
    assert "attachments/" not in str(log)


def test_splitik_attachment_upload_endpoint_returns_private_metadata(db, fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    api = FastAPI()
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_s3] = lambda: fake_s3
    api.dependency_overrides[get_actor_user_id] = lambda: USER_A
    api.include_router(splitik_router.router)
    client = TestClient(api)

    response = client.post(
        "/api/splitik/attachments",
        files={"file": ("receipt.jpg", b"\xff\xd8\xfffake-jpeg", "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "receipt.jpg"
    assert body["content_type"] == "image/jpeg"
    assert body["size_bytes"] == len(b"\xff\xd8\xfffake-jpeg")
    assert "bucket" not in body
    assert "key" not in body
    assert db.splitik_attachments.count_documents({"owner_user_id": USER_A}) == 1


def test_splitik_attachment_upload_works_without_object_storage(db, fake_s3, monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    api = FastAPI()
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_s3] = lambda: fake_s3
    api.dependency_overrides[get_actor_user_id] = lambda: USER_A
    api.include_router(splitik_router.router)
    client = TestClient(api)

    response = client.post(
        "/api/splitik/attachments",
        files={"file": ("receipt.jpg", b"\xff\xd8\xfffake-jpeg", "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "receipt.jpg"
    assert body["content_type"] == "image/jpeg"
    assert "content" not in body
    assert "bucket" not in body
    assert "key" not in body
    stored = db.splitik_attachments.find_one({"owner_user_id": USER_A})
    assert stored["storage"] == "mongo"
    assert stored["content"] == b"\xff\xd8\xfffake-jpeg"
    assert fake_s3.objects == {}


def test_splitik_attachment_rejects_mismatched_image_bytes(db, fake_s3, monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)

    with pytest.raises(HTTPException) as exc:
        splitik_attachments.create_attachment(
            db,
            fake_s3,
            actor_user_id=USER_A,
            filename="receipt.png",
            content_type="image/png",
            content=b"not-a-png",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Attachment content does not match image type."
    assert db.splitik_attachments.count_documents({"owner_user_id": USER_A}) == 0


def test_splitik_attachment_upload_daily_limit(db, fake_s3, monkeypatch):
    monkeypatch.setenv("SPLITIK_ATTACHMENT_DAILY_LIMIT", "1")
    monkeypatch.delenv("S3_BUCKET", raising=False)

    splitik_attachments.create_attachment(
        db,
        fake_s3,
        actor_user_id=USER_A,
        filename="receipt-1.jpg",
        content_type="image/jpeg",
        content=b"\xff\xd8\xfffirst",
    )
    with pytest.raises(HTTPException) as exc:
        splitik_attachments.create_attachment(
            db,
            fake_s3,
            actor_user_id=USER_A,
            filename="receipt-2.jpg",
            content_type="image/jpeg",
            content=b"\xff\xd8\xffsecond",
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "Splitik attachment daily limit exceeded."
    assert db.splitik_attachments.count_documents({"owner_user_id": USER_A}) == 1


def test_splitik_message_hourly_limit_is_enforced(db, monkeypatch):
    monkeypatch.setenv("SPLITIK_MESSAGE_HOURLY_LIMIT", "1")
    seed_users(db)
    _mock_llm(monkeypatch)

    splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Привет"),
        USER_A,
    )
    with pytest.raises(HTTPException) as exc:
        splitik.send_splitik_message(
            db,
            schemas.SplitikMessageRequest(mode="general", message="Еще вопрос"),
            USER_A,
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "Splitik hourly message limit exceeded."


def test_splitik_default_hourly_limit_allows_repeated_chat_retries(db, monkeypatch):
    monkeypatch.delenv("SPLITIK_MESSAGE_HOURLY_LIMIT", raising=False)
    seed_users(db)
    _mock_llm(monkeypatch)

    for index in range(11):
        response = splitik.send_splitik_message(
            db,
            schemas.SplitikMessageRequest(mode="general", message=f"Привет {index}"),
            USER_A,
        )

    assert response["intent"] == "chat"


def test_splitik_explains_user_scoped_spending_from_backend_facts(db, monkeypatch):
    seed_event(db)
    receipt = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="Dinner",
            total_amount_kopecks=10000,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="Meal",
                    cost_kopecks=10000,
                    share_items=[
                        schemas.CreateShareItemRequest(user_id=USER_A, share_value="0.5"),
                        schemas.CreateShareItemRequest(user_id=USER_B, share_value="0.5"),
                    ],
                )
            ],
        ),
        USER_A,
        idempotency_key="splitik-spending-test",
    )
    db.receipts.update_one({"id": receipt["id"]}, {"$set": {"status": "confirmed"}})
    calls = _mock_llm(monkeypatch)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Кто мне должен деньги?"),
        USER_A,
    )

    assert response["intent"] == "explain"
    summary = calls[0]["context"]["user_balance_summary"]
    assert summary["outstanding_owed_kopecks"] == 0
    assert summary["outstanding_receivable_kopecks"] == 5000
    assert summary["events"][0]["balances"][0]["debitor_id"] == USER_B
    assert summary["events"][0]["balances"][0]["creditor_id"] == USER_A


def test_splitik_refuses_private_friend_spending_outside_shared_context(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_users(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Куда тратит деньги Bob?"),
        USER_A,
    )

    assert calls == []
    assert response["intent"] == "refusal"
    assert response["guardrail_decision"]["reason"] == "private_friend_spending"


def test_seed_demo_friends_is_idempotent(db, monkeypatch):
    seed_users(db)
    db.users.update_one(
        {"id": USER_A},
        {
            "$set": {
                "name": "Илья Карсаков",
                "search_name": "илья карсаков",
                "public_handle": "ilya_karsakov",
            }
        },
    )
    module_path = Path(__file__).resolve().parents[1] / "tools" / "seed_demo_friends.py"
    spec = importlib.util.spec_from_file_location("seed_demo_friends", module_path)
    seed_demo_friends = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(seed_demo_friends)

    class FakeClient:
        def __getitem__(self, name):
            return db

    monkeypatch.setattr(seed_demo_friends, "MongoClient", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(seed_demo_friends, "build_mongodb_uri", lambda: "mongodb://unused")
    monkeypatch.setattr(
        "sys.argv",
        ["seed_demo_friends.py", "--user-name", "Илья Карсаков", "--confirm-local"],
    )

    assert seed_demo_friends.main() == 0
    assert seed_demo_friends.main() == 0
    assert db.users.count_documents({"public_handle": {"$regex": "_demo$"}}) == 6
    assert db.friends.count_documents({"requester_id": USER_A, "status": "accepted"}) == 6


def test_splitik_message_rejects_oversized_prompt():
    with pytest.raises(ValidationError):
        schemas.SplitikMessageRequest(message="x" * 8001)

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import schemas
from app.services import receipt_ai_drafts, splitik, splitik_llm
from tests.conftest import EVENT_ID, USER_A, USER_B, USER_C, seed_event, seed_users


def _mock_llm(monkeypatch):
    calls = []

    def fake_reply(*, system_prompt, user_message, context):
        calls.append(
            {
                "system_prompt": system_prompt,
                "user_message": user_message,
                "context": context,
            }
        )
        return "Сплитик: готово."

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)
    return calls


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
    requests = []

    def fake_get(url, headers, timeout):
        requests.append({"url": url, "headers": headers, "timeout": timeout})
        return _FakeResponse(
            body={
                "data": [
                    {"id": "primary-model"},
                    {"id": "verification-model"},
                    {"id": "escalation-model"},
                ]
            }
        )

    monkeypatch.setattr(splitik_llm.httpx, "get", fake_get)

    splitik_llm.validate_configured_models_available()

    assert requests[0]["url"] == "https://ai.example/v1/models"


def test_splitik_startup_validation_rejects_unavailable_runtime_model(monkeypatch):
    _set_llm_env(monkeypatch)

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


def test_splitik_draft_does_not_change_state_until_commit(db, monkeypatch):
    _mock_llm(monkeypatch)
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


def test_splitik_rejects_foreign_draft_commit(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_users(db)
    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Создай событие: Поездка"),
        USER_A,
    )

    with pytest.raises(HTTPException) as exc:
        splitik.commit_splitik_draft(db, response["drafts"][0]["id"], USER_B)

    assert exc.value.status_code == 404


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

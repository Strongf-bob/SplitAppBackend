import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import schemas
from app.dependencies import get_actor_user_id, get_db, get_s3
from app.routers import splitik as splitik_router
from app.services import receipt_ai_drafts, receipts, splitik, splitik_attachments, splitik_llm
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
            message="Поменяй сумму на 1500 рублей",
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


def test_splitik_draft_read_update_is_owner_scoped(db, monkeypatch):
    _mock_llm(monkeypatch)
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

    def fake_image_candidate(*, model_role, attachment_metadata, context):
        image_calls.append(
            {
                "model_role": model_role,
                "attachment_metadata": attachment_metadata,
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
    )

    assert image_calls[0]["attachment_metadata"]["id"] == attachment["id"]
    assert "key" not in image_calls[0]["attachment_metadata"]
    assert response["intent"] == "draft"
    draft = response["drafts"][0]
    assert draft["type"] == "create_receipt"
    assert draft["source"] == "image"
    assert draft["attachment_ids"] == [attachment["id"]]
    assert draft["payload"]["items"][0]["name"] == "Капучино"
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 0
    log = db.splitik_interactions.find_one({"message_id": response["message_id"]})
    assert log is not None
    assert "attachments/" not in str(log)
    assert "test-bucket" not in str(log)


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

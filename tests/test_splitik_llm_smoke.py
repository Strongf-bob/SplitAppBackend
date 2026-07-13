import pytest

from app.services import splitik_llm


def _set_smoke_env(monkeypatch):
    monkeypatch.setenv("SPLITIK_LLM_BASE_URL", "https://ai.example/v1")
    monkeypatch.setenv("SPLITIK_LLM_API_KEY", "test-key")
    monkeypatch.setenv("SPLITIK_PRIMARY_MODEL", "primary-model")
    monkeypatch.setenv("SPLITIK_FAST_CHAT_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("SPLITIK_INTENT_MODEL", "intent-model")
    monkeypatch.setenv("SPLITIK_VERIFICATION_MODEL", "verification-model")
    monkeypatch.setenv("SPLITIK_ESCALATION_MODEL", "escalation-model")
    monkeypatch.setenv("SPLITIK_VISION_MODEL", "minimax-m3")
    monkeypatch.setenv("SPLITIK_PRIMARY_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("SPLITIK_FAST_CHAT_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("SPLITIK_INTENT_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("SPLITIK_VERIFICATION_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("SPLITIK_ESCALATION_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("SPLITIK_VISION_TIMEOUT_SECONDS", "11")


def test_receipt_image_candidate_uses_vision_model_and_multimodal_content(monkeypatch):
    _set_smoke_env(monkeypatch)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"payload": json, "timeout": timeout})
        return _FakeSmokeResponse({"choices": [{"message": {"content": '{"payload": {}}'}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    candidate = splitik_llm.generate_receipt_image_candidate(
        model_role="vision",
        attachment_metadata=[{"id": "attachment-1", "content_type": "image/jpeg"}],
        image_urls=["https://signed.example/test-bucket/receipt.jpg?expires=900"],
        user_message="Это чек за ужин",
        context={"event_id": "event-1"},
    )

    assert candidate["model_role"] == "vision"
    assert candidate["model_id"] == "minimax-m3"
    assert calls[0]["timeout"] == 11.0
    assert calls[0]["payload"]["model"] == "minimax-m3"
    assert calls[0]["payload"]["messages"][1]["content"] == [
        {
            "type": "text",
            "text": (
                "Комментарий пользователя:\nЭто чек за ужин\n\n"
                "Метаданные вложений:\n[{'id': 'attachment-1', 'content_type': 'image/jpeg'}]\n\n"
                "Разрешенный backend context JSON:\n{'event_id': 'event-1'}\n\nВерни только JSON."
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": "https://signed.example/test-bucket/receipt.jpg?expires=900"},
        },
    ]


def test_splitik_llm_smoke_checks_each_configured_model_role(monkeypatch):
    _set_smoke_env(monkeypatch)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "model": json["model"], "timeout": timeout})
        return _FakeSmokeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    results = splitik_llm.smoke_check_configured_models()

    assert [result.model_role for result in results] == [
        "primary",
        "fast_chat",
        "intent",
        "verification",
        "escalation",
        "vision",
    ]
    assert [call["model"] for call in calls] == [
        "primary-model",
        "deepseek-v4-flash",
        "intent-model",
        "verification-model",
        "escalation-model",
        "minimax-m3",
    ]
    assert [call["timeout"] for call in calls] == [9, 4, 5, 7, 8, 11]


def test_splitik_llm_smoke_fails_when_model_exceeds_role_sla(monkeypatch):
    _set_smoke_env(monkeypatch)
    monkeypatch.setenv("SPLITIK_FAST_CHAT_TIMEOUT_SECONDS", "0.1")
    elapsed_values = iter([10.0, 10.2])

    def fake_monotonic():
        return next(elapsed_values)

    def fake_post(url, headers, json, timeout):
        return _FakeSmokeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(splitik_llm.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    with pytest.raises(RuntimeError, match="fast_chat.*exceeded SLA"):
        splitik_llm.smoke_check_configured_models(model_roles=["fast_chat"])


def test_fast_chat_retries_the_same_provider_with_primary_model(monkeypatch):
    _set_smoke_env(monkeypatch)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"model": json["model"], "timeout": timeout})
        if len(calls) == 1:
            raise splitik_llm.httpx.ConnectError("provider unavailable")
        return _FakeSmokeResponse({"choices": [{"message": {"content": "Готово."}}]})

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    reply = splitik_llm.generate_splitik_reply(
        system_prompt="system",
        user_message="привет",
        context={},
        model_role="fast_chat",
    )

    assert reply == "Готово."
    assert calls == [
        {"model": "deepseek-v4-flash", "timeout": 4.0},
        {"model": "primary-model", "timeout": 9.0},
    ]


def test_planner_retries_once_after_provider_read_timeout(monkeypatch):
    _set_smoke_env(monkeypatch)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"model": json["model"], "timeout": timeout})
        if len(calls) == 1:
            raise splitik_llm.httpx.ReadTimeout("provider timed out")
        return _FakeSmokeResponse(
            {"choices": [{"message": {"content": '{"intent":"none","actions":[]}'}}]}
        )

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    candidate = splitik_llm.generate_splitik_plan_candidate(
        user_message="Помоги создать событие для совместных расходов",
        context={},
    )

    assert candidate["content"] == {"intent": "none", "actions": []}
    assert calls == [
        {"model": "primary-model", "timeout": 9.0},
        {"model": "primary-model", "timeout": 9.0},
    ]


def test_planner_falls_back_to_fast_model_after_two_primary_read_timeouts(monkeypatch):
    _set_smoke_env(monkeypatch)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"model": json["model"], "timeout": timeout})
        if len(calls) < 3:
            raise splitik_llm.httpx.ReadTimeout("primary provider timed out")
        return _FakeSmokeResponse(
            {"choices": [{"message": {"content": '{"intent":"none","actions":[]}'}}]}
        )

    monkeypatch.setattr(splitik_llm.httpx, "post", fake_post)

    candidate = splitik_llm.generate_splitik_plan_candidate(
        user_message="Создай чек на 200 рублей",
        context={},
    )

    assert candidate["model_role"] == "fast_chat"
    assert candidate["model_id"] == "deepseek-v4-flash"
    assert candidate["content"] == {"intent": "none", "actions": []}
    assert calls == [
        {"model": "primary-model", "timeout": 9.0},
        {"model": "primary-model", "timeout": 9.0},
        {"model": "deepseek-v4-flash", "timeout": 4.0},
    ]


def test_splitik_configured_models_answer_within_role_sla(monkeypatch):
    if splitik_llm._env("SPLITIK_LLM_SMOKE_TEST") != "1":
        pytest.skip("Set SPLITIK_LLM_SMOKE_TEST=1 to run live Splitik LLM smoke checks.")

    results = splitik_llm.smoke_check_configured_models()

    assert results
    assert {result.model_role for result in results} >= {"primary", "fast_chat"}


def test_splitik_vision_model_accepts_multimodal_receipt_image():
    if splitik_llm._env("SPLITIK_LLM_SMOKE_TEST") != "1":
        pytest.skip("Set SPLITIK_LLM_SMOKE_TEST=1 to run live Splitik LLM smoke checks.")

    candidate = splitik_llm.generate_receipt_image_candidate(
        model_role="vision",
        attachment_metadata=[{"id": "smoke-image", "content_type": "image/png"}],
        image_urls=[
            "https://raw.githubusercontent.com/github/explore/main/topics/python/python.png"
        ],
        user_message="Тестовое изображение чека для проверки формата.",
        context={
            "event_id": "00000000-0000-0000-0000-000000000000",
            "attachment_ids": ["smoke-image"],
            "human_review_required": True,
        },
    )

    assert candidate["model_role"] == "vision"
    assert candidate["model_id"] == "minimax-m3"
    assert isinstance(candidate["content"], dict)


class _FakeSmokeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body

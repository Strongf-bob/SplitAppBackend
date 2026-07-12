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
    monkeypatch.setenv("SPLITIK_PRIMARY_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("SPLITIK_FAST_CHAT_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("SPLITIK_INTENT_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("SPLITIK_VERIFICATION_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("SPLITIK_ESCALATION_TIMEOUT_SECONDS", "8")


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
    ]
    assert [call["model"] for call in calls] == [
        "primary-model",
        "deepseek-v4-flash",
        "intent-model",
        "verification-model",
        "escalation-model",
    ]
    assert [call["timeout"] for call in calls] == [9, 4, 5, 7, 8]


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


def test_splitik_configured_models_answer_within_role_sla(monkeypatch):
    if splitik_llm._env("SPLITIK_LLM_SMOKE_TEST") != "1":
        pytest.skip("Set SPLITIK_LLM_SMOKE_TEST=1 to run live Splitik LLM smoke checks.")

    results = splitik_llm.smoke_check_configured_models()

    assert results
    assert {result.model_role for result in results} >= {"primary", "fast_chat"}


class _FakeSmokeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body

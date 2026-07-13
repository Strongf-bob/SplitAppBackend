import json
import logging


def test_emit_splitik_trace_redacts_credentials_and_preserves_review_fields(caplog):
    from app.core.splitik_trace import emit_splitik_trace

    with caplog.at_level(logging.INFO, logger="splitapp"):
        emit_splitik_trace(
            request_id="request-1",
            message_id="message-1",
            system_prompt="system prompt text",
            user_message="Bearer very-secret-token",
            assistant_message="https://storage.example/private?X-Amz-Signature=secret",
            model_ids=["deepseek-v4-pro"],
            context={"Authorization": "Bearer very-secret-token", "event": {"id": "event-1"}},
            tool_calls=[{"name": "splitik.get_event", "status": "completed"}],
            guardrail_decision={"allowed": True},
            latency_ms=12.5,
            status="success",
            stage="completed",
        )

    record = json.loads(caplog.records[-1].message)
    assert record["message"] == "splitik_review_trace"
    assert record["system_prompt_sha256"]
    assert record["model_ids"] == ["deepseek-v4-pro"]
    assert record["tool_calls"] == [{"name": "splitik.get_event", "status": "completed"}]
    assert "very-secret-token" not in json.dumps(record)
    assert "X-Amz-Signature" not in json.dumps(record)


def test_emit_splitik_trace_keeps_raw_content_disabled_by_default(caplog):
    from app.core.splitik_trace import emit_splitik_trace

    with caplog.at_level(logging.INFO, logger="splitapp"):
        emit_splitik_trace(
            request_id="request-1",
            message_id="message-1",
            system_prompt="system prompt text",
            user_message="team-only message",
            assistant_message="team-only answer",
            model_ids=[],
            context={},
            tool_calls=[],
            guardrail_decision={},
            latency_ms=1,
            status="success",
            stage="completed",
        )

    record = json.loads(caplog.records[-1].message)
    assert "system_prompt" not in record
    assert "user_message" not in record
    assert "assistant_message" not in record

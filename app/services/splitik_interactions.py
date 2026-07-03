from pymongo.database import Database

from app.services.common import new_uuid, utc_now
from app.services.splitik_guardrails import sanitize_message


def log_interaction(
    db: Database,
    *,
    actor_user_id: str,
    session_id: str,
    message_id: str,
    sanitized_user_message: str,
    intent: str,
    context_scope: str,
    assistant_message: str,
    guardrail_decision: dict,
    request_id: str | None = None,
    input_type: str = "text",
    model_ids: list[str] | None = None,
    structured_response: dict | None = None,
    tool_calls: list[dict] | None = None,
    draft_ids: list[str] | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
) -> dict:
    document = {
        "id": new_uuid(),
        "request_id": request_id,
        "session_id": session_id,
        "actor_user_id": actor_user_id,
        "message_id": message_id,
        "input_type": input_type,
        "sanitized_user_message": sanitize_message(sanitized_user_message),
        "intent": intent,
        "context_scope": context_scope,
        "model_ids": model_ids or [],
        "assistant_message": assistant_message,
        "structured_response": structured_response or {},
        "guardrail_decision": guardrail_decision,
        "tool_calls": tool_calls or [],
        "draft_ids": draft_ids or [],
        "latency_ms": latency_ms,
        "error": error,
        "created_at": utc_now(),
    }
    db.splitik_interactions.insert_one(document)
    return document

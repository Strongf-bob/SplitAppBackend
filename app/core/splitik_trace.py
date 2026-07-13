"""Structured, credential-safe traces consumed by the remote log reviewer."""

import hashlib
import json
import logging
import os
import re
from typing import Any


logger = logging.getLogger("splitapp")
_SECRET_KEY = re.compile(r"(authorization|token|api[_-]?key|secret|signature|cookie)", re.I)
_BEARER = re.compile(r"bearer\s+[^\s,]+", re.I)
_PRESIGNED = re.compile(r"([?&](?:X-Amz-[^=&]+|signature|token)=[^&\s]+)", re.I)


def _redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _PRESIGNED.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    return value


def _include_raw_content() -> bool:
    return os.getenv("SPLITIK_REVIEW_TRACE_INCLUDE_CONTENT", "false").strip().lower() == "true"


def emit_splitik_trace(
    *,
    request_id: str | None,
    message_id: str,
    system_prompt: str,
    user_message: str,
    assistant_message: str,
    model_ids: list[str],
    context: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    guardrail_decision: dict[str, Any],
    latency_ms: float,
    status: str,
    stage: str,
) -> None:
    record: dict[str, Any] = {
        "level": "INFO",
        "message": "splitik_review_trace",
        "request_id": request_id,
        "message_id": message_id,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "model_ids": model_ids,
        "context": _redact(context),
        "tool_calls": _redact(tool_calls),
        "guardrail_decision": _redact(guardrail_decision),
        "latency_ms": latency_ms,
        "status": status,
        "stage": stage,
    }
    if _include_raw_content():
        record.update(
            system_prompt=_redact(system_prompt),
            user_message=_redact(user_message),
            assistant_message=_redact(assistant_message),
        )
    logger.info(json.dumps(record, default=str, separators=(",", ":")))

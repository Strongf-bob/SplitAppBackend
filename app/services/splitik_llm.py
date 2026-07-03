import os
from dataclasses import dataclass
import json
from typing import Literal

import httpx
from fastapi import HTTPException


@dataclass(frozen=True)
class SplitikLLMConfig:
    base_url: str
    api_key: str
    primary_model: str
    verification_model: str | None
    escalation_model: str | None
    timeout_seconds: float

    @property
    def model_ids(self) -> set[str]:
        return {
            model
            for model in {self.primary_model, self.verification_model, self.escalation_model}
            if model
        }


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.")
    return value


def is_llm_configured() -> bool:
    return bool(
        _env("SPLITIK_LLM_BASE_URL")
        or _env("SPLITIK_LLM_API_KEY")
        or _env("SPLITIK_PRIMARY_MODEL")
        or _env("SPLITIK_VERIFICATION_MODEL")
        or _env("SPLITIK_ESCALATION_MODEL")
        or _env("SPLITIK_LLM_MODEL")
    )


def load_config() -> SplitikLLMConfig:
    try:
        timeout = float(os.getenv("SPLITIK_LLM_TIMEOUT_SECONDS", "20"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.") from exc

    primary_model = _env("SPLITIK_PRIMARY_MODEL") or _env("SPLITIK_LLM_MODEL")
    if not primary_model:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.")

    return SplitikLLMConfig(
        base_url=_required_env("SPLITIK_LLM_BASE_URL"),
        api_key=_required_env("SPLITIK_LLM_API_KEY"),
        primary_model=primary_model,
        verification_model=_env("SPLITIK_VERIFICATION_MODEL") or None,
        escalation_model=_env("SPLITIK_ESCALATION_MODEL") or None,
        timeout_seconds=timeout,
    )


def _model_for_role(
    config: SplitikLLMConfig, model_role: Literal["primary", "verification", "escalation"]
) -> str:
    model_by_role = {
        "primary": config.primary_model,
        "verification": config.verification_model,
        "escalation": config.escalation_model,
    }
    model = model_by_role[model_role]
    if not model:
        raise HTTPException(
            status_code=503, detail="Splitik receipt draft models are not configured."
        )
    return model


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _extract_chat_content(response_body: object) -> str:
    try:
        content = response_body["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM response was invalid.") from exc

    reply = str(content).strip()
    if not reply:
        raise HTTPException(status_code=502, detail="Splitik LLM response was empty.")
    return reply


def _parse_json_object(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Splitik LLM JSON response was invalid."
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Splitik LLM JSON response was invalid.")
    return parsed


def _models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return f"{normalized}/models"


def _extract_model_ids(response_body: object) -> set[str]:
    if isinstance(response_body, dict):
        data = response_body.get("data", [])
    else:
        data = response_body

    model_ids: set[str] = set()
    if not isinstance(data, list):
        return model_ids
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
        else:
            model_id = item
        if isinstance(model_id, str) and model_id.strip():
            model_ids.add(model_id.strip())
    return model_ids


def validate_configured_models_available() -> None:
    if not is_llm_configured():
        return

    try:
        config = load_config()
    except HTTPException as exc:
        raise RuntimeError("Splitik LLM runtime configuration is incomplete.") from exc

    try:
        response = httpx.get(
            _models_url(config.base_url),
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=config.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError("Could not validate Splitik LLM models.") from exc

    if response.status_code in {401, 403}:
        raise RuntimeError("Splitik LLM credentials were rejected during startup validation.")
    if response.status_code >= 400:
        raise RuntimeError("Splitik LLM provider model validation failed.")

    try:
        available_models = _extract_model_ids(response.json())
    except ValueError as exc:
        raise RuntimeError("Splitik LLM provider returned invalid model metadata.") from exc

    missing_models = sorted(config.model_ids - available_models)
    if missing_models:
        raise RuntimeError("Configured Splitik LLM models are not available.")


def generate_splitik_reply(*, system_prompt: str, user_message: str, context: dict) -> str:
    config = load_config()

    payload = {
        "model": config.primary_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User message:\n{user_message}\n\nAllowed backend context JSON:\n{context}"
                ),
            },
        ],
        "temperature": 0.2,
    }

    try:
        response = httpx.post(
            _chat_completions_url(config.base_url),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=config.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=503, detail="Splitik LLM credentials were rejected.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Splitik LLM provider returned an error.")

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM response was invalid.") from exc

    return _extract_chat_content(body)


def generate_receipt_draft_candidate(
    *,
    model_role: str,
    system_prompt: str,
    user_message: str,
    context: dict,
) -> dict:
    config = load_config()
    if model_role not in {"primary", "verification", "escalation"}:
        raise HTTPException(status_code=400, detail="Invalid Splitik model role.")
    model = _model_for_role(config, model_role)  # type: ignore[arg-type]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User receipt source:\n{user_message}\n\n"
                    f"Allowed backend context JSON:\n{context}\n\n"
                    "Return only JSON."
                ),
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    try:
        response = httpx.post(
            _chat_completions_url(config.base_url),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=config.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=503, detail="Splitik LLM credentials were rejected.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Splitik LLM provider returned an error.")

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM response was invalid.") from exc

    return {
        "model_role": model_role,
        "model_id": model,
        "content": _parse_json_object(_extract_chat_content(body)),
    }


def generate_receipt_image_candidate(
    *,
    model_role: str,
    attachment_metadata: dict,
    context: dict,
) -> dict:
    return generate_receipt_draft_candidate(
        model_role=model_role,
        system_prompt=(
            "You create SplitApp receipt drafts from receipt image metadata and "
            "OCR/vision input. Return only JSON in the receipt draft shape."
        ),
        user_message=f"Receipt image attachment metadata:\n{attachment_metadata}",
        context=context,
    )

import json
import os
from dataclasses import dataclass
import time
from typing import Literal

import httpx
from fastapi import HTTPException


_MODEL_QUARANTINE_UNTIL: dict[str, float] = {}


@dataclass(frozen=True)
class SplitikLLMConfig:
    base_url: str
    api_key: str
    primary_model: str
    fast_chat_model: str
    intent_model: str | None
    verification_model: str | None
    escalation_model: str | None
    vision_model: str
    timeout_seconds: float

    @property
    def model_ids(self) -> set[str]:
        configured_models = {
            model
            for model in {
                self.primary_model,
                self.fast_chat_model,
                self.intent_model,
                self.verification_model,
                self.escalation_model,
                self.vision_model,
            }
            if model
        }
        configured_models.update(_model_pool("SPLITIK_TEXT_MODEL_POOL", self.fast_chat_model))
        configured_models.update(_model_pool("SPLITIK_VISION_MODEL_POOL", self.vision_model))
        return configured_models


@dataclass(frozen=True)
class SplitikLLMSmokeResult:
    model_role: str
    model_id: str
    elapsed_ms: float
    timeout_seconds: float


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
        or _env("SPLITIK_FAST_CHAT_MODEL")
        or _env("SPLITIK_INTENT_MODEL")
        or _env("SPLITIK_VERIFICATION_MODEL")
        or _env("SPLITIK_ESCALATION_MODEL")
        or _env("SPLITIK_VISION_MODEL")
        or _env("SPLITIK_LLM_MODEL")
    )


def load_config() -> SplitikLLMConfig:
    try:
        timeout = float(os.getenv("SPLITIK_LLM_TIMEOUT_SECONDS", "12"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.") from exc

    primary_model = _env("SPLITIK_PRIMARY_MODEL") or _env("SPLITIK_LLM_MODEL")
    if not primary_model:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.")

    return SplitikLLMConfig(
        base_url=_required_env("SPLITIK_LLM_BASE_URL"),
        api_key=_required_env("SPLITIK_LLM_API_KEY"),
        primary_model=primary_model,
        fast_chat_model=_env("SPLITIK_FAST_CHAT_MODEL")
        or _env("SPLITIK_INTENT_MODEL")
        or "deepseek-v4-flash",
        intent_model=_env("SPLITIK_INTENT_MODEL") or None,
        verification_model=_env("SPLITIK_VERIFICATION_MODEL") or None,
        escalation_model=_env("SPLITIK_ESCALATION_MODEL") or None,
        vision_model=_env("SPLITIK_VISION_MODEL") or "minimax-m3",
        timeout_seconds=timeout,
    )


def _role_timeout(config: SplitikLLMConfig, model_role: str) -> float:
    timeout_by_role = {
        "primary": os.getenv("SPLITIK_PRIMARY_TIMEOUT_SECONDS"),
        "fast_chat": os.getenv("SPLITIK_FAST_CHAT_TIMEOUT_SECONDS"),
        "intent": os.getenv("SPLITIK_INTENT_TIMEOUT_SECONDS"),
        "verification": os.getenv("SPLITIK_VERIFICATION_TIMEOUT_SECONDS"),
        "escalation": os.getenv("SPLITIK_ESCALATION_TIMEOUT_SECONDS"),
        "vision": os.getenv("SPLITIK_VISION_TIMEOUT_SECONDS"),
    }
    raw_timeout = timeout_by_role.get(model_role)
    if model_role == "fast_chat" and not raw_timeout:
        return min(config.timeout_seconds, 12)
    if not raw_timeout:
        return config.timeout_seconds
    try:
        return float(raw_timeout)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.") from exc


def _model_for_role(
    config: SplitikLLMConfig,
    model_role: Literal["primary", "fast_chat", "intent", "verification", "escalation", "vision"],
) -> str:
    model_by_role = {
        "primary": config.primary_model,
        "fast_chat": config.fast_chat_model,
        "intent": config.intent_model or config.primary_model,
        "verification": config.verification_model,
        "escalation": config.escalation_model,
        "vision": config.vision_model,
    }
    model = model_by_role[model_role]
    if not model:
        raise HTTPException(
            status_code=503, detail="Splitik receipt draft models are not configured."
        )
    return model


def _model_pool(name: str, default_model: str) -> list[str]:
    configured = [value.strip() for value in _env(name).split(",") if value.strip()]
    models = configured or [default_model]
    return list(dict.fromkeys(models))


def _fallback_model(config: SplitikLLMConfig, model_role: str, current_model: str) -> str | None:
    if model_role in {"primary", "fast_chat", "intent"}:
        candidates = _model_pool("SPLITIK_TEXT_MODEL_POOL", current_model)
    elif model_role == "vision":
        candidates = _model_pool("SPLITIK_VISION_MODEL_POOL", current_model)
    else:
        candidates = [current_model]
    now = time.monotonic()
    return next(
        (
            candidate
            for candidate in candidates
            if candidate != current_model and _MODEL_QUARANTINE_UNTIL.get(candidate, 0) <= now
        ),
        None,
    )


def _preferred_model(config: SplitikLLMConfig, model_role: str) -> str:
    default_model = _model_for_role(config, model_role)  # type: ignore[arg-type]
    if model_role in {"primary", "fast_chat", "intent"}:
        candidates = _model_pool("SPLITIK_TEXT_MODEL_POOL", default_model)
    elif model_role == "vision":
        candidates = _model_pool("SPLITIK_VISION_MODEL_POOL", default_model)
    else:
        candidates = [default_model]
    now = time.monotonic()
    return next(
        (candidate for candidate in candidates if _MODEL_QUARANTINE_UNTIL.get(candidate, 0) <= now),
        default_model,
    )


def _quarantine_seconds() -> float:
    try:
        return float(_env("SPLITIK_MODEL_QUARANTINE_SECONDS") or "600")
    except ValueError:
        return 600.0


def _quarantine_model(model: str) -> None:
    _MODEL_QUARANTINE_UNTIL[model] = time.monotonic() + _quarantine_seconds()


def _mark_model_healthy(model: str) -> None:
    _MODEL_QUARANTINE_UNTIL.pop(model, None)


def reset_model_quarantines() -> None:
    _MODEL_QUARANTINE_UNTIL.clear()


def _configured_model_roles(config: SplitikLLMConfig) -> list[str]:
    roles = ["primary", "fast_chat"]
    if config.intent_model:
        roles.append("intent")
    if config.verification_model:
        roles.append("verification")
    if config.escalation_model:
        roles.append("escalation")
    roles.append("vision")
    return roles


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def smoke_check_configured_models(
    *,
    model_roles: list[str] | None = None,
) -> list[SplitikLLMSmokeResult]:
    config = load_config()
    roles = model_roles or _configured_model_roles(config)
    results: list[SplitikLLMSmokeResult] = []

    for role in roles:
        if role not in {"primary", "fast_chat", "intent", "verification", "escalation", "vision"}:
            raise RuntimeError(f"Splitik LLM smoke role is invalid: {role}")

        model = _model_for_role(config, role)  # type: ignore[arg-type]
        timeout_seconds = _role_timeout(config, role)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return a short health-check response. No private data.",
                },
                {"role": "user", "content": "health check"},
            ],
            "temperature": 0,
        }

        started = time.monotonic()
        try:
            response = httpx.post(
                _chat_completions_url(config.base_url),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Splitik LLM smoke {role} model {model} exceeded SLA {timeout_seconds:.2f}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Splitik LLM smoke {role} model {model} request failed.") from exc

        elapsed_seconds = time.monotonic() - started
        if elapsed_seconds > timeout_seconds:
            raise RuntimeError(
                f"Splitik LLM smoke {role} model {model} exceeded SLA "
                f"{timeout_seconds:.2f}s: {elapsed_seconds:.2f}s."
            )
        if response.status_code in {401, 403}:
            raise RuntimeError(f"Splitik LLM smoke {role} model {model} credentials rejected.")
        if response.status_code >= 400:
            raise RuntimeError(
                f"Splitik LLM smoke {role} model {model} provider returned "
                f"HTTP {response.status_code}."
            )

        try:
            content = _extract_chat_content(response.json())
        except (HTTPException, ValueError) as exc:
            raise RuntimeError(f"Splitik LLM smoke {role} model {model} response invalid.") from exc
        if not content:
            raise RuntimeError(f"Splitik LLM smoke {role} model {model} response empty.")

        results.append(
            SplitikLLMSmokeResult(
                model_role=role,
                model_id=model,
                elapsed_ms=round(elapsed_seconds * 1000, 2),
                timeout_seconds=timeout_seconds,
            )
        )

    return results


def probe_model_pools() -> dict[str, str]:
    """Probe configured text and vision pools and quarantine failed candidates."""
    config = load_config()
    probes = [
        ("text", model, None)
        for model in _model_pool("SPLITIK_TEXT_MODEL_POOL", config.fast_chat_model)
    ]
    vision_fixture_url = _env("SPLITIK_VISION_SMOKE_IMAGE_URL")
    expected_vision_total = _env("SPLITIK_VISION_SMOKE_EXPECTED_TOTAL_KOPECKS")
    if vision_fixture_url:
        probes.extend(
            ("vision", model, vision_fixture_url)
            for model in _model_pool("SPLITIK_VISION_MODEL_POOL", config.vision_model)
        )

    results: dict[str, str] = {}
    for capability, model, fixture_url in probes:
        user_content: str | list[dict] = "health check"
        if fixture_url:
            user_content = [
                {
                    "type": "text",
                    "text": "Return only JSON with payload and questions for this receipt.",
                },
                {"type": "image_url", "image_url": {"url": fixture_url}},
            ]
        try:
            response = httpx.post(
                _chat_completions_url(config.base_url),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return a short health-check response. No private data.",
                        },
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0,
                    **({"response_format": {"type": "json_object"}} if fixture_url else {}),
                },
                timeout=_role_timeout(config, "vision" if fixture_url else "fast_chat"),
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}")
            content = _extract_chat_content(response.json())
            if fixture_url:
                parsed = _parse_json_object(content)
                if not isinstance(parsed.get("payload"), dict):
                    raise RuntimeError("vision fixture response lacks payload")
                if (
                    expected_vision_total
                    and str(parsed["payload"].get("total_amount_kopecks")) != expected_vision_total
                ):
                    raise RuntimeError("vision fixture total does not match")
        except (httpx.HTTPError, HTTPException, RuntimeError, ValueError):
            _quarantine_model(model)
            results[f"{capability}:{model}"] = "unhealthy"
        else:
            _mark_model_healthy(model)
            results[f"{capability}:{model}"] = "healthy"
    return results


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
    fence_start = cleaned.find("```")
    if fence_start >= 0:
        fence_end = cleaned.find("```", fence_start + 3)
        if fence_end > fence_start:
            cleaned = cleaned[fence_start + 3 : fence_end].strip()
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


def generate_splitik_reply(
    *,
    system_prompt: str,
    user_message: str,
    context: dict,
    model_role: Literal["primary", "fast_chat"] = "primary",
) -> str:
    config = load_config()

    current_model = _preferred_model(config, model_role)
    try:
        reply = _generate_splitik_reply_for_role(
            config=config,
            system_prompt=system_prompt,
            user_message=user_message,
            context=context,
            model_role=model_role,
            model_override=current_model,
        )
        _mark_model_healthy(current_model)
        return reply
    except HTTPException as exc:
        _quarantine_model(current_model)
        if model_role != "fast_chat" or exc.status_code != 502:
            raise
        fallback_model = _fallback_model(config, model_role, current_model)
        if fallback_model:
            reply = _generate_splitik_reply_for_role(
                config=config,
                system_prompt=system_prompt,
                user_message=user_message,
                context=context,
                model_role=model_role,
                model_override=fallback_model,
            )
            _mark_model_healthy(fallback_model)
            return reply
        return _generate_splitik_reply_for_role(
            config=config,
            system_prompt=system_prompt,
            user_message=user_message,
            context=context,
            model_role="primary",
        )


def _generate_splitik_reply_for_role(
    *,
    config: SplitikLLMConfig,
    system_prompt: str,
    user_message: str,
    context: dict,
    model_role: Literal["primary", "fast_chat"],
    model_override: str | None = None,
) -> str:
    model = model_override or _model_for_role(config, model_role)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Сообщение пользователя:\n{user_message}\n\n"
                    f"Разрешенный backend context JSON:\n{context}"
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
            timeout=_role_timeout(config, model_role),
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


def _generate_json_candidate(
    *,
    model_role: str,
    system_prompt: str,
    user_label: str,
    user_message: str,
    context: dict,
    user_content: str | list[dict] | None = None,
) -> dict:
    config = load_config()
    if model_role not in {"primary", "intent", "verification", "escalation", "vision"}:
        raise HTTPException(status_code=400, detail="Invalid Splitik model role.")
    model = _preferred_model(config, model_role)
    fallback_model = _fallback_model(config, model_role, model)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_content
                if user_content is not None
                else (
                    f"{user_label}:\n{user_message}\n\n"
                    f"Разрешенный backend context JSON:\n{context}\n\n"
                    "Верни только JSON."
                ),
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    request_kwargs = {
        "headers": {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        "json": payload,
        "timeout": _role_timeout(config, model_role),
    }
    response_model_role = model_role
    try:
        response = httpx.post(_chat_completions_url(config.base_url), **request_kwargs)
    except httpx.ReadTimeout:
        try:
            response = httpx.post(_chat_completions_url(config.base_url), **request_kwargs)
        except httpx.ReadTimeout as exc:
            _quarantine_model(model)
            if fallback_model:
                model = fallback_model
                fallback_request_kwargs = {
                    **request_kwargs,
                    "json": {**payload, "model": model},
                }
                try:
                    response = httpx.post(
                        _chat_completions_url(config.base_url), **fallback_request_kwargs
                    )
                    response_model_role = model_role
                except httpx.HTTPError as fallback_exc:
                    raise HTTPException(
                        status_code=502, detail="Splitik LLM request failed."
                    ) from fallback_exc
            elif model_role != "primary":
                raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc
            else:
                model = _model_for_role(config, "fast_chat")
                fallback_request_kwargs = {
                    **request_kwargs,
                    "json": {**payload, "model": model},
                    "timeout": _role_timeout(config, "fast_chat"),
                }
                try:
                    response = httpx.post(
                        _chat_completions_url(config.base_url), **fallback_request_kwargs
                    )
                    response_model_role = "fast_chat"
                except httpx.HTTPError as fallback_exc:
                    raise HTTPException(
                        status_code=502, detail="Splitik LLM request failed."
                    ) from fallback_exc
        except httpx.HTTPError as exc:
            _quarantine_model(model)
            if fallback_model:
                model = fallback_model
                fallback_request_kwargs = {
                    **request_kwargs,
                    "json": {**payload, "model": model},
                }
                try:
                    response = httpx.post(
                        _chat_completions_url(config.base_url), **fallback_request_kwargs
                    )
                    response_model_role = model_role
                except httpx.HTTPError as fallback_exc:
                    raise HTTPException(
                        status_code=502, detail="Splitik LLM request failed."
                    ) from fallback_exc
            else:
                raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc
    except httpx.HTTPError as exc:
        _quarantine_model(model)
        if fallback_model:
            model = fallback_model
            fallback_request_kwargs = {**request_kwargs, "json": {**payload, "model": model}}
            try:
                response = httpx.post(
                    _chat_completions_url(config.base_url), **fallback_request_kwargs
                )
                response_model_role = model_role
            except httpx.HTTPError as fallback_exc:
                raise HTTPException(
                    status_code=502, detail="Splitik LLM request failed."
                ) from fallback_exc
        else:
            raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc

    if response.status_code in {401, 403}:
        _quarantine_model(model)
        if fallback_model and model != fallback_model:
            model = fallback_model
            fallback_request_kwargs = {**request_kwargs, "json": {**payload, "model": model}}
            try:
                response = httpx.post(
                    _chat_completions_url(config.base_url), **fallback_request_kwargs
                )
                response_model_role = model_role
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=503, detail="Splitik LLM credentials were rejected.")
    if response.status_code >= 400:
        _quarantine_model(model)
        if fallback_model and model != fallback_model:
            model = fallback_model
            fallback_request_kwargs = {**request_kwargs, "json": {**payload, "model": model}}
            try:
                response = httpx.post(
                    _chat_completions_url(config.base_url), **fallback_request_kwargs
                )
                response_model_role = model_role
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Splitik LLM provider returned an error.")

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM response was invalid.") from exc

    _mark_model_healthy(model)
    return {
        "model_role": response_model_role,
        "model_id": model,
        "content": _parse_json_object(_extract_chat_content(body)),
    }


def generate_receipt_draft_candidate(
    *,
    model_role: str,
    system_prompt: str,
    user_message: str,
    context: dict,
) -> dict:
    return _generate_json_candidate(
        model_role=model_role,
        system_prompt=system_prompt,
        user_label="Источник чека пользователя",
        user_message=user_message,
        context=context,
    )


def generate_event_draft_candidate(*, user_message: str, context: dict) -> dict:
    return _generate_json_candidate(
        model_role="primary",
        system_prompt=(
            "Ты извлекаешь намерение создания события SplitApp из сообщения пользователя. "
            "Если пользователь явно просит создать событие, верни JSON: "
            '{"intent":"create_event","payload":{"name":"короткое название события"},'
            '"assistant_message":"естественный Markdown-ответ без emoji, что создан черновик '
            'и его нужно подтвердить"}. '
            "Название должно быть осмысленным и коротким: убирай служебные фразы вроде "
            '"создай событие", сохраняй место, участников или повод, если они есть. '
            'Если пользователь пишет follow-up вроде "просто создай событие" без нового '
            "названия, восстанови название из recent_messages в backend context. "
            'Фразы-запреты и настройки вроде "не добавляй чеков", "без чеков", '
            '"пока не добавляй расходы" никогда не должны становиться названием события; '
            "учитывай их только в assistant_message. "
            'Если намерения создать событие нет, верни {"intent":"none"}. '
            "Не утверждай, что событие уже создано окончательно: создан только черновик."
        ),
        user_label="Сообщение пользователя",
        user_message=user_message,
        context=context,
    )


def generate_splitik_plan_candidate(*, user_message: str, context: dict) -> dict:
    return _generate_json_candidate(
        model_role="primary",
        system_prompt=(
            "Ты planner Splitik. Верни только JSON-план, без текста вне JSON. "
            "Backend считает твой JSON недоверенным и сам валидирует все поля. "
            "Разрешенные action type: create_event_draft, create_event_bundle_draft, create_receipt_draft, "
            "update_receipt_draft, ask_clarifying_question. "
            "Нельзя возвращать delete_event, payment, database, mongo, raw_query, "
            "mark_payment_paid, confirm_receipt или любые tool calls. "
            "Если пользователь просит создать несколько сущностей, верни несколько actions. "
            "Если фото переданы без OCR/vision текста, не притворяйся что прочитал чек: "
            "верни ask_clarifying_question. "
            "Форма ответа: "
            '{"intent":"create_drafts|ask_clarifying_question|none",'
            '"assistant_message":"короткий Markdown-ответ без emoji",'
            '"actions":[{"type":"create_event_draft","payload":{"name":"..."}},'
            '{"type":"create_event_bundle_draft","payload":{"name":"...",'
            '"participant_ids":["uuid"],"receipts":[{"title":"...",'
            '"amount_kopecks":10000,"payer_id":"uuid","split":"equal"}]}},'
            '{"type":"create_receipt_draft","event_id":"uuid","payload":{...},'
            '"attachment_ids":["uuid"],"questions":[]},'
            '{"type":"update_receipt_draft","draft_id":"uuid","event_id":"uuid",'
            '"payload":{...},"questions":[]},'
            '{"type":"ask_clarifying_question","questions":[{"id":"...","text":"...",'
            '"required":true}]}]}. '
            "Receipt payload должен соответствовать CreateReceiptRequest: суммы в копейках, "
            "payer_id и share_items.user_id только из backend context."
        ),
        user_label="Сообщение пользователя",
        user_message=user_message,
        context=context,
    )


def generate_splitik_intent_candidate(*, user_message: str, context: dict) -> dict:
    return _generate_json_candidate(
        model_role="intent",
        system_prompt=(
            "Ты intent-router Splitik. Перед JSON planner нужно понять, что хочет "
            "пользователь. Верни только JSON. "
            "intent должен быть одним из: explain, chat, mutation. "
            "mutation - пользователь просит создать событие, добавить чек, изменить "
            "черновик, разобрать фото чека или выполнить действие с данными SplitApp. "
            "explain - пользователь просит пояснить, почему он должен, кто кому должен, "
            "как посчиталась сумма, что произошло в событии, или просит краткую сводку. "
            "chat - обычный вопрос/ответ без создания или изменения данных. "
            "Если сомневаешься между explain/chat и mutation, выбирай mutation только "
            "при явном глаголе действия: создай, добавь, измени, обнови, распарси, "
            "разбери чек, загрузи. "
            'Форма ответа: {"intent":"explain|chat|mutation","confidence":0.0,'
            '"reason":"короткая причина без персональных данных"}.'
        ),
        user_label="Сообщение пользователя",
        user_message=user_message,
        context=context,
    )


def generate_receipt_image_candidate(
    *,
    model_role: str,
    attachment_metadata: list[dict],
    image_urls: list[str],
    user_message: str,
    context: dict,
) -> dict:
    image_parts = [
        {"type": "image_url", "image_url": {"url": image_data_url}} for image_data_url in image_urls
    ]
    return _generate_json_candidate(
        model_role=model_role,
        system_prompt=(
            "Ты создаешь черновик чека SplitApp по фото. Верни только JSON в форме "
            '{"payload":{...},"questions":[...]}. Поля payload должны соответствовать '
            "CreateReceiptRequest: суммы в копейках, payer_id и share_items.user_id "
            "только из backend context. Если поле нельзя надежно извлечь, не выдумывай "
            "его и добавь уточняющий вопрос. Не утверждай, что чек уже добавлен: "
            "backend создаст только черновик."
        ),
        user_label="Комментарий пользователя",
        user_message=user_message,
        context=context,
        user_content=[
            {
                "type": "text",
                "text": (
                    f"Комментарий пользователя:\n{user_message}\n\n"
                    f"Метаданные вложений:\n{attachment_metadata}\n\n"
                    f"Разрешенный backend context JSON:\n{context}\n\nВерни только JSON."
                ),
            },
            *image_parts,
        ],
    )

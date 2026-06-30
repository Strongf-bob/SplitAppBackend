import os

import httpx
from fastapi import HTTPException


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="Splitik LLM is not configured.")
    return value


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def generate_splitik_reply(*, system_prompt: str, user_message: str, context: dict) -> str:
    base_url = _required_env("SPLITIK_LLM_BASE_URL")
    api_key = _required_env("SPLITIK_LLM_API_KEY")
    model = _required_env("SPLITIK_LLM_MODEL")
    timeout = float(os.getenv("SPLITIK_LLM_TIMEOUT_SECONDS", "20"))

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "User message:\n"
                    f"{user_message}\n\n"
                    "Allowed backend context JSON:\n"
                    f"{context}"
                ),
            },
        ],
        "temperature": 0.2,
    }

    try:
        response = httpx.post(
            _chat_completions_url(base_url),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM request failed.") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=503, detail="Splitik LLM credentials were rejected.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Splitik LLM provider returned an error.")

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Splitik LLM response was invalid.") from exc

    reply = str(content).strip()
    if not reply:
        raise HTTPException(status_code=502, detail="Splitik LLM response was empty.")
    return reply

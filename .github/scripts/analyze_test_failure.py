#!/usr/bin/env python3
"""Explain failing PR tests with LLM context and post a GitHub PR comment."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


COMMENT_MARKER = "<!-- ai-test-failure-analysis -->"
MAX_LOG_CHARS = 30000
MAX_DIFF_CHARS = 45000


def log(message: str) -> None:
    print(f"[ai-test-failure-analysis] {message}", flush=True)


def read_text(path: Path, limit: int) -> str:
    if not path.exists():
        return f"[file not found: {path}]"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[unable to read {path}: {exc}]"
    if len(text) <= limit:
        return text
    return text[-limit:]


def github_request(method: str, url: str, token: str, payload: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else None


def llm_request(url: str, token: str, model: str, test_log: str, pr_diff: str) -> str:
    system_prompt = (
        "Ты senior backend engineer. Анализируй упавшие тесты в Pull Request. "
        "Пиши на русском, официально и кратко. Не выдумывай факты. "
        "Связывай traceback с изменениями PR, если связь видна из diff. "
        "Если причина неочевидна, явно напиши, какой информации не хватает. "
        "Не предлагай игнорировать тесты."
    )
    user_prompt = f"""
Нужно объяснить, почему упали тесты в backend PR.

Верни Markdown с такими разделами:

## AI Test Failure Analysis

**Краткий вывод:** одно-два предложения.

**Вероятная причина:** что именно сломалось и почему.

**Где смотреть:** файлы/тесты/строки из traceback или diff.

**Рекомендуемое исправление:** конкретные следующие действия.

Если падение не связано с diff, так и напиши.

## Test log

```text
{test_log}
```

## PR diff

```diff
{pr_diff}
```
"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM response does not contain choices.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM response does not contain message content.")
    return content.strip()


def main() -> int:
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    llm_url = os.environ.get("OCR_LLM_URL")
    llm_token = os.environ.get("OCR_LLM_AUTH_TOKEN")
    llm_model = os.environ.get("OCR_LLM_MODEL")
    test_exit_code = os.environ.get("TEST_EXIT_CODE", "unknown")

    if not github_token or not repo or not event_path:
        log("Missing GitHub environment; skipping analysis.")
        return 0
    if not llm_url or not llm_token or not llm_model:
        log("Missing OCR_LLM_URL, OCR_LLM_AUTH_TOKEN, or OCR_LLM_MODEL; skipping analysis.")
        return 0

    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pr_number = str((event.get("pull_request") or {}).get("number") or event.get("number") or "")
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Unable to read GitHub event payload: {exc}")
        return 0
    if not pr_number:
        log("No pull request number found; skipping analysis.")
        return 0

    test_log = read_text(Path(os.environ.get("TEST_LOG_FILE", "test-output.log")), MAX_LOG_CHARS)
    pr_diff = read_text(Path(os.environ.get("PR_DIFF_FILE", "pr-diff.patch")), MAX_DIFF_CHARS)

    try:
        analysis = llm_request(llm_url, llm_token, llm_model, test_log, pr_diff)
    except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
        log(f"LLM analysis failed: {exc}")
        analysis = (
            "## AI Test Failure Analysis\n\n"
            "**Краткий вывод:** тесты упали, но AI-анализ не удалось выполнить.\n\n"
            f"**Техническая причина:** `{exc}`\n\n"
            "Проверьте artifact `ai-test-failure-context` с полным test log и PR diff."
        )

    body = (
        f"{COMMENT_MARKER}\n"
        f"{analysis}\n\n"
        "---\n"
        f"Test exit code: `{test_exit_code}`. "
        "Полный лог и diff доступны в artifact `ai-test-failure-context`."
    )
    try:
        github_request(
            "POST",
            f"{api_url}/repos/{repo}/issues/{pr_number}/comments",
            github_token,
            {"body": body},
        )
    except (urllib.error.URLError, RuntimeError) as exc:
        log(f"Unable to post PR comment: {exc}")
        return 0
    log("Posted AI test failure analysis comment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Splitik Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Splitik into a backend-controlled MVP AI agent that creates and edits drafts from text/photo inputs, explains user-scoped spending, enforces guardrails, and logs every interaction for regression analysis.

**Architecture:** The LLM never calls MongoDB or arbitrary APIs. Splitik router accepts user messages, then service code builds bounded context, validates model output, runs backend-owned AgentTools, persists drafts/logs, and returns safe assistant responses. All writes remain draft-first until a checked commit endpoint applies existing domain services.

**Tech Stack:** FastAPI, Pydantic, PyMongo/mongomock, existing SplitApp service layer, OpenAI-compatible chat completions adapter, pytest.

## Global Constraints

- Backend repository scope only: do not patch the iOS repository.
- Keep API behavior, `openapi.yaml`, tests, and docs in sync.
- LLM does not get direct MongoDB access or arbitrary API execution.
- Every write flow is draft-first and requires explicit confirmation before changing money state.
- Do not log secrets, auth tokens, private storage URLs, payment credentials, or raw production credentials.
- Every privacy or guardrail fix requires regression tests.
- Preserve unrelated dirty worktree changes and stage only Splitik MVP files.

---

## File Structure

- `app/schemas.py`: public request/response schemas for Splitik intents, questions, guardrails, drafts, interactions, and attachment references.
- `app/services/splitik_guardrails.py`: deterministic pre/post guardrail rules for domain scope, homework refusal, secrets, privacy, and forbidden operations.
- `app/services/splitik_tools.py`: backend-owned operations for bounded reads, universal draft creation/update, and draft commit.
- `app/services/splitik_interactions.py`: sanitized interaction logging into `splitik_interactions`.
- `app/services/splitik.py`: orchestrates sessions, context, LLM calls, guardrails, tools, drafts, and response shaping.
- `app/services/splitik_llm.py`: OpenAI-compatible structured response and receipt/image draft helpers.
- `app/routers/splitik.py`: message, draft read/update/commit, and optional attachment endpoints.
- `app/main.py`: runtime model validation during lifespan when LLM config exists.
- `tests/test_splitik.py`: existing Splitik tests plus new workflow, privacy, draft, guardrail, and logging cases.
- `tests/test_app_config.py`: startup validation test only if not already covered in Splitik tests.
- `docs/wiki/Splitik-Agent.md`: user-facing backend docs for MVP behavior and safety boundaries.
- `docs/wiki/API-Reference.md`: endpoint table updates.
- `openapi.yaml`: generated runtime contract.

---

### Task 1: Contract, Guardrails, and Interaction Logging Foundation

**Files:**
- Modify: `app/schemas.py`
- Create: `app/services/splitik_guardrails.py`
- Create: `app/services/splitik_interactions.py`
- Modify: `app/services/splitik.py`
- Test: `tests/test_splitik.py`

**Interfaces:**
- Produces: `schemas.SplitikGuardrailDecision`, `schemas.SplitikQuestion`, `schemas.SplitikSuggestedAction`, `schemas.SplitikInteractionLog`.
- Produces: `splitik_guardrails.evaluate_user_message(message: str, *, context_scope: str) -> dict`.
- Produces: `splitik_guardrails.evaluate_structured_response(response: dict, *, capabilities: list[str]) -> dict`.
- Produces: `splitik_interactions.log_interaction(db, *, actor_user_id: str, session_id: str, message_id: str, request_id: str | None, input_type: str, sanitized_user_message: str, intent: str, context_scope: str, model_ids: list[str], assistant_message: str, structured_response: dict, guardrail_decision: dict, tool_calls: list[dict], draft_ids: list[str], latency_ms: float | None, error: str | None) -> dict`.

- [ ] **Step 1: Write failing guardrail/logging tests**

Add tests to `tests/test_splitik.py`:

```python
def test_splitik_refuses_homework_and_logs_interaction(db, monkeypatch):
    calls = _mock_llm(monkeypatch)

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
make test TESTS='tests/test_splitik.py::test_splitik_refuses_homework_and_logs_interaction tests/test_splitik.py::test_splitik_logs_allowed_message_without_tokens'
```

Expected: failures because `intent`, `guardrail_decision`, and `splitik_interactions` are not implemented.

- [ ] **Step 3: Implement schemas and deterministic guardrails**

Add schemas near existing Splitik schemas:

```python
class SplitikGuardrailDecision(BaseModel):
    allowed: bool
    reason: str
    message: str


class SplitikQuestion(BaseModel):
    id: str
    text: str
    required: bool = True


class SplitikSuggestedAction(BaseModel):
    type: str
    label: str
    draft_id: UUID | None = None
```

Create `app/services/splitik_guardrails.py`:

```python
import re

_HOMEWORK_MARKERS = (
    "домашк",
    "дз",
    "задачу по",
    "реши задачу",
    "алгебр",
    "геометр",
    "контрольн",
)
_SECRET_MARKERS = ("password", "пароль", "token", "api key", "секрет", "private key")
_FRIEND_PRIVATE_MARKERS = ("куда тратит", "траты друга", "на что тратит")


def _contains_any(message: str, markers: tuple[str, ...]) -> bool:
    lowered = message.casefold()
    return any(marker in lowered for marker in markers)


def decision(allowed: bool, reason: str, message: str) -> dict:
    return {"allowed": allowed, "reason": reason, "message": message}


def sanitize_message(message: str) -> str:
    sanitized = re.sub(r"Authorization:\s*Bearer\s+\S+", "Authorization: Bearer [REDACTED]", message, flags=re.I)
    sanitized = re.sub(r"token\s*=\s*\S+", "token=[REDACTED]", sanitized, flags=re.I)
    sanitized = re.sub(r"(api[_ -]?key|password|пароль)\s*[:=]\s*\S+", r"\1=[REDACTED]", sanitized, flags=re.I)
    return sanitized


def evaluate_user_message(message: str, *, context_scope: str = "general") -> dict:
    if _contains_any(message, _HOMEWORK_MARKERS):
        return decision(False, "out_of_scope_homework", "Я могу помогать только со SplitApp: событиями, чеками, долгами и личными тратами.")
    if _contains_any(message, _SECRET_MARKERS):
        return decision(False, "secret_request", "Не отправляйте пароли, токены, ключи или платежные секреты в чат.")
    if context_scope == "general" and _contains_any(message, _FRIEND_PRIVATE_MARKERS):
        return decision(False, "private_friend_spending", "Я не могу раскрывать личные траты другого пользователя вне общего события.")
    return decision(True, "allowed", "")


def evaluate_structured_response(response: dict, *, capabilities: list[str]) -> dict:
    operation = str(response.get("operation") or response.get("tool") or "")
    forbidden = operation.startswith("forbidden:") or operation in {
        "delete_event",
        "edit_existing_money_state",
        "mark_foreign_payment_paid",
        "impersonate_user",
    }
    if forbidden:
        return decision(False, "forbidden_operation", "Это действие заблокировано политикой безопасности SplitApp.")
    return decision(True, "allowed", "")
```

- [ ] **Step 4: Implement interaction logging and wire response fields**

Create `app/services/splitik_interactions.py`:

```python
from pymongo.database import Database

from app.services.common import new_uuid, utc_now
from app.services.splitik_guardrails import sanitize_message


def log_interaction(
    db: Database,
    *,
    actor_user_id: str,
    session_id: str,
    message_id: str,
    request_id: str | None = None,
    input_type: str = "text",
    sanitized_user_message: str,
    intent: str,
    context_scope: str,
    model_ids: list[str] | None = None,
    assistant_message: str,
    structured_response: dict | None = None,
    guardrail_decision: dict,
    tool_calls: list[dict] | None = None,
    draft_ids: list[str] | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
) -> dict:
    now = utc_now()
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
        "created_at": now,
    }
    db.splitik_interactions.insert_one(document)
    return document
```

Update `send_splitik_message` to evaluate user guardrails before calling LLM, return `intent` and `guardrail_decision`, and log both refusals and allowed messages.

- [ ] **Step 5: Run focused tests**

Run:

```bash
make test TESTS='tests/test_splitik.py::test_splitik_refuses_homework_and_logs_interaction tests/test_splitik.py::test_splitik_logs_allowed_message_without_tokens'
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/schemas.py app/services/splitik_guardrails.py app/services/splitik_interactions.py app/services/splitik.py tests/test_splitik.py
git commit -m "feat(splitik): add guardrail logging foundation" -m "Add deterministic Splitik guardrails and interaction logging so every message is policy-evaluated and auditable before broader agent workflows are introduced."
```

---

### Task 2: Universal Draft Tools for Event and Receipt Text Workflows

**Files:**
- Create: `app/services/splitik_tools.py`
- Modify: `app/services/splitik.py`
- Modify: `app/schemas.py`
- Test: `tests/test_splitik.py`

**Interfaces:**
- Consumes: `splitik_guardrails.evaluate_structured_response`.
- Produces: `splitik_tools.create_event_draft(db, *, actor_user_id: str, session_id: str, payload: dict, source: str = "text") -> dict`.
- Produces: `splitik_tools.create_receipt_draft(db, *, actor_user_id: str, session_id: str, event_id: str, payload: dict, source: str = "text") -> dict`.
- Produces: `splitik_tools.update_draft(db, *, actor_user_id: str, draft_id: str, patch: dict) -> dict`.
- Produces: `splitik_tools.commit_draft(db, *, actor_user_id: str, draft_id: str) -> dict`.

- [ ] **Step 1: Add failing tests for receipt draft and chat edit**

Add tests that assert a receipt draft is created from text without changing balances, and a follow-up message updates draft payload/version.

- [ ] **Step 2: Implement `splitik_tools.py`**

Create event and receipt draft helpers that persist the universal shape from the design. Validate receipt payload with `schemas.CreateReceiptRequest`. Commit `create_event` through `create_event`; commit `create_receipt` through `create_receipt` only when the user explicitly commits and an idempotency key is provided or generated.

- [ ] **Step 3: Wire text intent extraction**

Support deterministic MVP extraction:

- event draft when text contains `создай событие`, `новое событие`, or `event`;
- receipt draft when mode is `event` and text contains money markers such as `чек`, `счет`, `заплатил`, `₽`, `руб`;
- question response when event, payer, participants, or split details are missing.

- [ ] **Step 4: Run tests**

Run:

```bash
make test TESTS='tests/test_splitik.py'
```

Expected: Splitik tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/splitik_tools.py app/services/splitik.py app/schemas.py tests/test_splitik.py
git commit -m "feat(splitik): add universal draft tools" -m "Introduce backend-owned tools for event and receipt drafts so Splitik can create and update draft state without directly changing confirmed money records."
```

---

### Task 3: Draft API Endpoints and Commit Policy

**Files:**
- Modify: `app/routers/splitik.py`
- Modify: `app/services/splitik.py`
- Modify: `app/services/splitik_tools.py`
- Modify: `app/schemas.py`
- Test: `tests/test_splitik.py`

**Interfaces:**
- Consumes: `splitik_tools.update_draft`.
- Consumes: `splitik_tools.commit_draft`.
- Produces: `GET /api/splitik/drafts/{id}`.
- Produces: `PATCH /api/splitik/drafts/{id}`.
- Updates: `POST /api/splitik/drafts/{id}/commit` to support universal draft types.

- [ ] **Step 1: Add tests for owner-only draft read/update/commit**

Add router/service tests proving owner can read/update/commit and another user receives 404.

- [ ] **Step 2: Implement endpoints**

Expose draft read/update/commit through router with `get_actor_user_id` and owner-scoped service calls.

- [ ] **Step 3: Run tests**

Run:

```bash
make test TESTS='tests/test_splitik.py'
```

Expected: all Splitik tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/routers/splitik.py app/services/splitik.py app/services/splitik_tools.py app/schemas.py tests/test_splitik.py
git commit -m "feat(splitik): expose owner-scoped draft API" -m "Add read, update, and universal commit endpoints for Splitik drafts while preserving owner checks and draft-first behavior."
```

---

### Task 4: Attachment and Image Receipt Draft Flow

**Files:**
- Modify: `app/routers/splitik.py`
- Create: `app/services/splitik_attachments.py`
- Modify: `app/services/splitik.py`
- Modify: `app/services/splitik_llm.py`
- Modify: `app/schemas.py`
- Test: `tests/test_splitik.py`

**Interfaces:**
- Produces: `splitik_attachments.create_attachment(db, s3, *, actor_user_id: str, filename: str, content_type: str, content: bytes) -> dict`.
- Produces: `splitik_llm.generate_receipt_image_candidate(...) -> dict`.
- Consumes: `splitik_tools.create_receipt_draft`.

- [ ] **Step 1: Add mocked image draft test**

Test that an image attachment plus event context creates `create_receipt` draft with `source == "image"` and no balance changes.

- [ ] **Step 2: Implement private attachment metadata**

Persist attachment metadata without exposing private storage URLs in API response or logs.

- [ ] **Step 3: Implement mocked-provider-compatible image extraction**

Use a service function that can be monkeypatched in tests and maps provider output to `CreateReceiptRequest`.

- [ ] **Step 4: Run tests**

Run:

```bash
make test TESTS='tests/test_splitik.py'
```

Expected: all Splitik tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/routers/splitik.py app/services/splitik_attachments.py app/services/splitik.py app/services/splitik_llm.py app/schemas.py tests/test_splitik.py
git commit -m "feat(splitik): create receipt drafts from images" -m "Add private attachment handling and image-driven receipt draft creation so Splitik can turn uploaded receipt photos into reviewable drafts."
```

---

### Task 5: User-Scoped Expense Explanation Tools

**Files:**
- Modify: `app/services/splitik_tools.py`
- Modify: `app/services/splitik.py`
- Test: `tests/test_splitik.py`

**Interfaces:**
- Produces: `splitik_tools.read_user_balance_summary(db, *, actor_user_id: str) -> dict`.
- Produces: `splitik_tools.read_event_expense_explanation(db, *, actor_user_id: str, event_id: str) -> dict`.

- [ ] **Step 1: Add tests for allowed and forbidden explanations**

Test user can ask about own debts and shared event balance explanations, but cannot ask for private friend spending outside shared context.

- [ ] **Step 2: Implement summaries using existing balance services**

Build facts from memberships, receipts, payments, `get_event_balances`, and `get_event_balance_explanations`. Do not let LLM invent or recalculate money.

- [ ] **Step 3: Run tests**

Run:

```bash
make test TESTS='tests/test_splitik.py'
```

Expected: all Splitik tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/services/splitik_tools.py app/services/splitik.py tests/test_splitik.py
git commit -m "feat(splitik): explain user-scoped spending" -m "Add backend-computed spending and debt explanation tools so Splitik can explain personal balances without exposing unrelated friend data."
```

---

### Task 6: Runtime Model Validation, OpenAPI, and Docs

**Files:**
- Modify: `app/main.py`
- Modify: `docs/wiki/Splitik-Agent.md`
- Modify: `docs/wiki/API-Reference.md`
- Modify: `openapi.yaml`
- Test: `tests/test_app_config.py`
- Test: `tests/test_splitik.py`

**Interfaces:**
- Consumes: `splitik_llm.validate_configured_models_available()`.

- [ ] **Step 1: Add startup validation test**

Test that lifespan calls model validation when Splitik LLM config is present and does not call it when config is absent.

- [ ] **Step 2: Wire startup validation**

Call `splitik_llm.validate_configured_models_available()` in `lifespan` after environment loading and before serving requests.

- [ ] **Step 3: Regenerate OpenAPI**

Run:

```bash
.venv/bin/python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, ensure_ascii=False))' > openapi.yaml
```

- [ ] **Step 4: Update docs**

Document MVP behaviors, endpoints, guardrails, logging, and explicit frontend/iOS follow-up boundaries.

- [ ] **Step 5: Run verification**

Run:

```bash
make test
make lint
make format-check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py docs/wiki/Splitik-Agent.md docs/wiki/API-Reference.md openapi.yaml tests/test_app_config.py tests/test_splitik.py
git commit -m "docs(splitik): sync agent MVP contract" -m "Wire runtime model validation and synchronize OpenAPI plus documentation with the Splitik MVP agent contract."
```

---

## Final Verification

- [ ] Run `make test`.
- [ ] Run `make lint`.
- [ ] Run `make format-check`.
- [ ] Run `git diff --check`.
- [ ] Confirm `git status --short` contains only intended Splitik MVP files plus pre-existing unrelated dirty files.
- [ ] Push `strongf/splitik-agent-mvp` only after verification is green or explicitly report any pre-existing blocker.

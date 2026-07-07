# Splitik Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Splitik's single-intent heuristics with a backend-validated JSON planner that supports multiple drafts, all attachments, safer receipt parsing, and event-scoped draft updates.

**Architecture:** Add internal planner schemas and an LLM planner wrapper. Route event-mode and general-mode draft creation through the planner, validate all actions server-side, and keep all mutations as pending drafts until commit.

**Tech Stack:** FastAPI, Pydantic v2, PyMongo, pytest, existing Splitik services.

## Global Constraints

- Public Splitik message API remains compatible.
- LLM output is untrusted and must be validated before database writes.
- Backend creates drafts only; confirmed money state changes only through explicit commit.
- Keep OpenAPI unchanged unless public schemas change.

---

### Task 1: Planner Tests

**Files:**
- Modify: `tests/test_splitik.py`

**Interfaces:**
- Consumes: `splitik_llm.generate_splitik_plan_candidate`
- Produces: failing tests for planner behavior.

- [x] Add tests for multiple event drafts from one message.
- [x] Add tests that all attachment metadata is passed to the planner.
- [x] Add tests for planner receipt JSON creating a receipt draft.
- [x] Add tests that unsupported planner actions create no drafts.
- [x] Add tests that active receipt draft updates are scoped to the current event.
- [x] Add tests for server-enforced per-user limits.

### Task 2: Planner Models And LLM Wrapper

**Files:**
- Modify: `app/services/splitik_llm.py`
- Modify: `app/services/splitik_guardrails.py`

**Interfaces:**
- Produces: `generate_splitik_plan_candidate(user_message: str, context: dict) -> dict`
- Produces: `evaluate_planner_action(action: dict) -> dict`

- [x] Add a JSON planner LLM call with strict system prompt.
- [x] Add action-level guardrail checks for forbidden operation names and raw database/operator keys.

### Task 3: Planner Execution

**Files:**
- Modify: `app/services/splitik.py`
- Modify: `app/services/splitik_tools.py`

**Interfaces:**
- Consumes: planner candidate from Task 2.
- Produces: validated `create_event` and `create_receipt` drafts.

- [x] Route draft creation through planner first.
- [x] Support multiple event drafts.
- [x] Support existing-event receipt drafts from structured JSON.
- [x] Pass all attachments to the planner.
- [x] Scope active receipt draft lookup by event id.
- [x] Preserve simple fallback only when planner produces no draft.
- [x] Enforce Splitik, draft, event, receipt, and attachment limits.

### Task 4: Verification And Explanation

**Files:**
- Modify: `docs/wiki/Splitik-Agent.md`

**Interfaces:**
- Consumes: final implementation.
- Produces: user-facing chain explanation.

- [x] Run targeted regression tests for new limits.
- [ ] Run `make test`, `make lint`, and `git diff --check`.
- [x] Update docs to describe user request -> planner -> validation -> draft -> commit.
- [ ] Report the chain in plain Russian.

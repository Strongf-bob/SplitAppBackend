# Splitik receipt vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route event-chat images to a `minimax-m3` vision request and create only a receipt draft.

**Architecture:** Attachment storage returns authenticated image bytes internally while preserving the existing sanitized public metadata API. The Splitik service routes image messages before intent/planner handling. The LLM service uses a dedicated `vision` role and builds an OpenAI-compatible multimodal user message.

**Tech Stack:** FastAPI, PyMongo, S3-compatible object storage, httpx, pytest, GitHub Actions.

## Global Constraints

- Use the existing OpenAI-compatible provider URL and API key.
- Send the image only to the `vision` request; never persist image bytes, data URLs, bucket names, or keys in logs.
- Keep money changes draft-first; a vision result must not commit a receipt.

---

### Task 1: Secure attachment retrieval and direct image routing

**Files:**
- Modify: `app/services/splitik_attachments.py`
- Modify: `app/services/splitik.py`
- Modify: `app/routers/splitik.py`
- Test: `tests/test_splitik.py`

- [ ] Write a failing event-image test that asserts the intent/planner functions are not called, the internal image bytes reach the vision candidate, and the outcome is a pending receipt draft.
- [ ] Run: `python -m pytest tests/test_splitik.py::test_splitik_routes_event_image_to_vision_receipt_draft -q`; expect failure because the route still calls the text planner and primary model.
- [ ] Add an authenticated internal attachment reader and pass S3 to the message service. Route event attachments before intent classification.
- [ ] Run the focused test; expect PASS.

### Task 2: Dedicated multimodal vision role

**Files:**
- Modify: `app/services/splitik_llm.py`
- Modify: `tests/test_splitik_llm_smoke.py`

- [ ] Write failing tests that expect `vision` to select `SPLITIK_VISION_MODEL` and send an `image_url` content part containing the supplied data URL.
- [ ] Run focused LLM tests; expect failure because `vision` is not a recognized role.
- [ ] Add the role, timeout, model selection, and JSON multimodal request implementation.
- [ ] Run focused tests; expect PASS.

### Task 3: Deployment configuration and regression verification

**Files:**
- Modify: `.env.example`
- Modify: `.github/workflows/ci.yml`

- [ ] Configure `SPLITIK_VISION_MODEL=minimax-m3` and propagate it through smoke and deployment env handling.
- [ ] Run: `make test`, `make lint`, `make format-check`, and `git diff --check`.
- [ ] Commit with a conventional commit, merge to `main`, push, and verify CI/deploy plus the production vision configuration.

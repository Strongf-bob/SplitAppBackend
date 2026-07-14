# Whole Codebase Refactor Implementation Plan

> Historical plan. Its PWA work is retired as of 2026-07-14; current client work belongs to the native iOS application.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate Splitik presentation from page orchestration and remove duplicate session-history reads without changing contracts.

**Architecture:** `page.tsx` remains the PWA composition root. `splitik-chat.tsx` owns chat rendering and exposes only data and callbacks. The Splitik service passes its loaded session to every helper that needs recent history.

**Tech Stack:** FastAPI, PyMongo, pytest, Next.js, React, TypeScript, node:test.

## Global Constraints

- Preserve API/OpenAPI behaviour and existing Russian user-visible copy.
- Do not change financial, authorization, or confirmation behaviour.
- Keep user-owned untracked files outside this worktree untouched.

---

### Task 1: Prove the backend session boundary

**Files:**
- Modify: `tests/test_splitik.py`
- Modify: `app/services/splitik.py`

- [ ] Add a test that loads a session with six messages, calls the planner context with that session, and monkeypatches `splitik_tools.read_recent_session_messages` to fail. Assert the passed session messages are retained in chronological order.
- [ ] Run `.venv/bin/pytest tests/test_splitik.py -k planner_context -q`; expect failure because the helper has no session argument and calls storage.
- [ ] Add `session: dict` to `_planner_context`, `_planner_draft_result`, and `_maybe_create_draft`; use `list(session.get("messages", []))[-6:]` for planner context and thread the loaded session from `send_splitik_message`.
- [ ] Run `.venv/bin/pytest tests/test_splitik.py -q`; expect all Splitik tests to pass.

### Task 2: Extract the Splitik UI boundary

**Files:**
- Create: `web/src/components/splitik-chat.tsx`
- Modify: `web/src/app/page.tsx`
- Modify: `web/tests/pwa-ui-contract.test.mjs`

- [ ] Add a node contract that requires `SplitikScreen` to be exported by `splitik-chat.tsx` and requires `page.tsx` to import it instead of declaring it.
- [ ] Run `node --test web/tests/pwa-ui-contract.test.mjs`; expect the new extraction assertion to fail.
- [ ] Move `ChatMessage`, visual-viewport hook, chat screen, draft card/sheet, markdown parser, and Splitik-only helpers into `splitik-chat.tsx`. Keep callback signatures and `data-testid` values exactly unchanged.
- [ ] Import `SplitikScreen` and `ChatMessage` into `page.tsx`, deleting the moved code and unused icon/component imports.
- [ ] Run `node --test web/tests/pwa-ui-contract.test.mjs`; expect all contracts to pass.

### Task 3: Integrate and verify

**Files:** scoped files from Tasks 1-2.

- [ ] Run `make test`, `make lint`, `make format-check`, `npm run lint`, `npm run typecheck`, `npm run build`, and `git diff --check`.
- [ ] Inspect the diff to confirm only the scoped service, page/component, tests, and design documentation changed.
- [ ] Commit the refactor with a Conventional Commit after review.

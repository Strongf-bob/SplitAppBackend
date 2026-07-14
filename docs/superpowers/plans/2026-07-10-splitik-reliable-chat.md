# Splitik Reliable Chat Implementation Plan

> Historical plan. Its PWA work is retired as of 2026-07-14; current client work belongs to the native iOS application.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Splitik keyboard-safe on mobile, reliably create explicit event drafts, and provide manual recovery after failures.

**Architecture:** The PWA uses a visual-viewport-aware flex chat and retains failed messages for retry. The backend extracts clear general-mode create-event commands before the LLM chain and uses the already-loaded session when constructing context.

**Tech Stack:** Next.js, React, TypeScript, FastAPI, MongoDB, node:test, pytest.

## Global Constraints

- Keep blue-and-white SplitApp styling and explicit draft confirmation.
- Never disable browser zoom; prevent only Safari input auto-zoom with a 16px textarea.
- Do not touch unrelated untracked files.

---

### Task 1: Failing contracts

**Files:** `web/tests/pwa-ui-contract.test.mjs`, `tests/test_splitik.py`.

- [ ] Add a PWA test requiring `useVisualViewportHeight`, `data-testid="splitik-message-end"`, a `text-[16px]` input, a non-fixed composer, `Создать событие вручную`, and `Повторить отправку`.
- [ ] Run `node --test web/tests/pwa-ui-contract.test.mjs`; it must fail because those behaviours do not exist.
- [ ] Add a pytest case that sends `Создай событие Такси до дома`, asserts one `create_event` draft named `Такси до дома`, and fails the test if an intent-model function is called.
- [ ] Run `.venv/bin/pytest tests/test_splitik.py -k explicit_event_command -q`; it must fail before implementation.

### Task 2: Short deterministic backend path

**Files:** `app/services/splitik.py`, `tests/test_splitik.py`.

- [ ] Add `_explicit_event_name(message: str) -> str | None` using this extraction rule: `re.match(r"^\\s*(?:давай\\s+)?(?:создай|создать|добавь|добавить)\\s+(?:новое\\s+)?событи[ея]\\s*(?:про|:|-)?\\s*(.+?)\\s*$", message, re.IGNORECASE)`. Strip punctuation, reject invalid names, and limit to 80 characters.
- [ ] In general mode, call that function before `_classify_user_intent`; for a result call `splitik_tools.create_event_draft` and return the existing pending-confirmation response without an LLM call.
- [ ] Change `_build_tool_results` to receive the loaded `session` and use `list(session.get("messages", []))[-6:]`, instead of calling `read_recent_session_messages` a second time.
- [ ] Run `.venv/bin/pytest tests/test_splitik.py -q` and confirm all Splitik tests pass.

### Task 3: Keyboard-safe chat and recovery

**Files:** `web/src/app/page.tsx`, `web/src/app/globals.css`, `web/public/sw.js`, `web/tests/pwa-ui-contract.test.mjs`.

- [ ] Add `useVisualViewportHeight(enabled: boolean)` that subscribes to `visualViewport` `resize` and `scroll`, returns the visible pixel height, and cleans up on unmount.
- [ ] Extend `ChatMessage` with `delivery?: "failed"`; on abort/fetch failure retain the user message, append recovery copy, and render `Повторить отправку`.
- [ ] Give `SplitikScreen` an `onCreateEventManually(message)` callback. In the parent set `newEventName`, set event creation open, clear selection, and navigate to `events`.
- [ ] Make the Splitik screen a height-bound flex column, use a scrollable list with `data-testid="splitik-message-end"`, and use a normal composer in the column rather than `fixed`. Scroll on focus, visual-viewport resize, send, and response only while near the bottom.
- [ ] Use `text-[16px]`, `resize-none`, and controlled auto-height for the textarea.
- [ ] Bump both PWA cache markers to `splitapp-next-pwa-v37`.
- [ ] Run `node --test web/tests/pwa-ui-contract.test.mjs web/tests/pwa-cache-contract.test.mjs web/tests/pwa-settlement-contract.test.mjs` and `npm run typecheck` from `web/`.

### Task 4: End-to-end verification

**Files:** scoped files from Tasks 1–3 plus this plan.

- [ ] Run `make test`, `make lint`, `npm run build` from `web/`, and `git diff --check`.
- [ ] Run the PWA locally and inspect 375px and 430px mobile viewports: focus, last message visibility, textarea scale, manual recovery action, and draft card.
- [ ] Commit only scoped implementation files with `fix(splitik): make mobile chat resilient`.

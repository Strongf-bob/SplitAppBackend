# Whole Codebase Refactor Design

> Historical design. The PWA runtime was removed on 2026-07-14; current client work belongs to the native iOS application.

## Goal

Reduce the maintenance cost of the backend-served SplitApp PWA while preserving all existing HTTP contracts, authorization boundaries, and user-visible flows.

## Scope

- Move Splitik chat presentation and formatting out of the application page.
- Pass the already-loaded Splitik session through draft/planner helpers instead of loading its message history again.
- Make the extracted UI boundary explicit through exported props and focused contract tests.
- Preserve `openapi.yaml`, endpoints, payloads, cache behaviour, and the existing Russian UI copy.

## Non-goals

- No schema migration, new endpoint, changed payment/settlement lifecycle, or authentication change.
- No rewrite of stable services merely to reduce line counts.

## Approach

The PWA application page remains the composition root: it owns routing, data loading, and mutations. A new `splitik-chat` component owns only visual-viewport behaviour, chat rendering, retry controls, and draft cards. Splitik-specific formatting helpers live with that component rather than in the page.

The backend continues to load a session once in `send_splitik_message`. That session is passed to draft/planner context builders, which derive the bounded recent history in memory. This removes duplicate Mongo reads while keeping message ordering and the LLM context unchanged.

## Verification

Tests will establish the new boundaries first, then the backend and frontend suites, lint, typecheck, production build, and whitespace checks will run on the final diff.

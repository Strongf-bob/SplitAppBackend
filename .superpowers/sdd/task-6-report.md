# Task 6 report

## Scope

- Implemented the backend-served PWA settlement flow inside the existing event detail screen.
- Touched only frontend/PWA files and tests; no backend code, OpenAPI, or docs were changed.
- Preserved the existing SplitApp visual system: Montserrat, blue/white surfaces, rounded cards, no new green fintech palette and no new bottom-nav item.

## RED

- Added `web/tests/pwa-settlement-contract.test.mjs` before implementation.
- Initial RED command:
  - `node --test web/tests/*.test.mjs`
- RED result:
  - 73 tests total, 66 passed, 7 failed.
  - Expected failures covered missing settlement component extraction, missing exact API types/actions, missing parallel event load/cache, missing approval/payment copy separation, missing payment-request role actions, missing accessibility/touch markers, and missing v35 cache bump.

## GREEN

- Final verification commands:
  - `node --test web/tests/*.test.mjs` -> 73 passed, 0 failed.
  - `npm run typecheck` from `web` -> passed.
  - `npm run lint` from `web` -> passed.
  - `npm run build` from `web` -> passed.
- Installed web dependencies with `npm ci` from the existing `web/package-lock.json`; dependency versions were not changed.

## Files

- Created `web/src/components/settlement-panel.tsx`
  - Focused settlement UI/component.
  - Handles preview states, selected plan rendering, approvals/rejection reason, execute, payment request status display, debtor mark-paid, receiver confirmation, accessible errors, loading/disabled states, and terminal-plan refresh/new-plan paths.
- Modified `web/src/app/page.tsx`
  - Added per-event settlement cache.
  - Event open now loads receipts, settlement preview, settlement plans, and payment requests in parallel with `Promise.allSettled`.
  - Settlement panel is embedded below event summary/participants and before receipts.
  - Added settlement refresh/report wiring through the existing authenticated API and `notifyProblem` path.
- Modified `web/src/lib/splitapp-api.ts`
  - Added exact TypeScript API types for settlement preview, plan, edge, approval, payment requests, payment, and raw balance explanations.
- Created `web/tests/pwa-settlement-contract.test.mjs`
  - Source/UI contract tests for endpoints/actions, copy separation, component extraction, parallel load/cache, accessibility/touch markers, and cache bump.
- Modified `web/tests/pwa-ui-contract.test.mjs`
  - Updated PWA shell version contract to v35.
- Modified `web/public/sw.js`
  - Bumped service worker cache name to `splitapp-next-pwa-v35`.

## Commit

- Branch: `strongf/intra-event-settlement`
- Commit subject: `feat(pwa): add event settlement plan experience`
- Final commit hash: reported in the task handoff after commit creation.

## Self-review

- Backend scope preserved: no files under `app/`, `tests/`, `docs/`, or `openapi.yaml` were changed.
- The settlement flow is inside `EventDetailScreen`, not a separate technical dashboard or new nav item.
- Approval and payment are deliberately separated in copy and actions:
  - `Согласиться с планом` says it is not payment.
  - `Создать запросы на оплату` says it does not mark money paid.
  - `Я оплатил` is debtor-only for requested payment requests.
  - `Подтвердить получение` is creditor-only when a paid request exposes `payment_id`.
- Create plan, execute plan, and mark-paid use `Idempotency-Key: crypto.randomUUID()`.
- Payment requests are loaded from `GET /api/events/{id}/payment-requests?limit=100`, so linked paid requests can expose `payment_id`.
- Latest relevant plan selection prioritizes pending/approved/executing/partially_settled before completed/terminal plans.
- Error states are user-facing and recoverable, with `role="alert"`, `aria-live`, retry paths, and parent `notifyProblem` reporting.
- Touch targets use existing button sizing with `min-h-11`/`min-h-12`; focus rings are visible and blue.

## Remaining visual risks

- Browser visual QA was not run in this task because the controller will perform it later.
- Needs screenshot validation at 375px and desktop for dense real data: long names, many approvers, many edges, and mixed request statuses.
- The panel uses source-contract accessibility/touch markers, but real keyboard/focus traversal should still be checked in Browser QA.

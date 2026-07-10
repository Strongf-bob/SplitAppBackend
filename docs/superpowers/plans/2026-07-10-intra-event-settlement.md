# Intra-Event Settlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Every behavior change follows test-driven development.

**Goal:** Safely simplify debts inside one event and let participants approve and pay the recommended transfers without changing receipt history or trusting client-calculated money.

**Architecture:** The receipt/payment ledger remains immutable source truth. `balances.py` exposes both pairwise raw debts and deterministic globally netted debts; ordinary confirmed payments are included before global netting, so payment of a simplified edge reduces the correct net positions. A read-only preview can be persisted as a snapshot-backed plan; all participants present in the source debt graph approve before uniquely keyed payment requests are materialized.

**Tech Stack:** FastAPI, Pydantic, MongoDB/Mongomock, integer kopecks, pytest, existing idempotency/audit/domain-event helpers, backend-served Next.js PWA.

## Global Constraints

- Scope is exactly one event; no cross-event aggregation or settlement.
- Receipts and their shares are never rewritten by netting.
- Raw pairwise debts remain available for explanation and audit.
- Simplified debts are computed from confirmed receipts and confirmed payments only.
- A preview or approved plan is not proof of payment.
- Only receiver-confirmed payments reduce balances.
- Backend calculates every amount, participant and edge; the client submits no financial graph.
- All money uses positive integer kopecks.
- Every state mutation enforces authenticated membership, event-open state, snapshot freshness where applicable, idempotency and audit/domain events.
- No automatic approval or payment confirmation on timeout.
- All source participants, including net-zero intermediaries, must approve a persisted plan.
- Every generated payment request has a stable settlement edge ID and a database uniqueness guard.

---

### Task 1: Globally simplified intra-event balances

**Files:**
- Create: `app/services/settlement_algorithm.py`
- Create: `tests/test_settlement_algorithm.py`
- Modify: `app/services/balances.py`
- Modify: `app/services/__init__.py`
- Modify: `tests/test_services.py`

**Interfaces:**
- `build_settlement_edges(balance_rows: list[dict]) -> list[dict]`
- `get_event_raw_balances(db, event_id, actor_user_id) -> list[dict]`
- `get_event_balances(db, event_id, actor_user_id) -> list[dict]` returns globally simplified rows.
- `get_event_balance_explanations(...)` continues exposing pairwise receipt/payment contributions.

- [ ] Write failing tests for the Vanya/Katya/Petya cycle, deterministic ties, conservation, empty balances, and invalid rows.
- [ ] Verify the tests fail because global netting is absent.
- [ ] Implement the pure deterministic debtor/creditor matcher.
- [ ] Preserve current pairwise calculation as `get_event_raw_balances`; simplify those rows in `get_event_balances`.
- [ ] Add a regression test proving a confirmed payment along a simplified edge reduces the payer/receiver global net positions correctly.
- [ ] Run focused tests, then all service tests.
- [ ] Commit as `feat(balances): add global intra-event debt simplification`.

### Task 2: Read-only settlement preview and explanation

**Files:**
- Modify: `app/schemas.py`
- Create: `app/services/settlements.py`
- Modify: `app/services/__init__.py`
- Modify: `app/routers/events.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_app_config.py`

**Interfaces:**
- `get_settlement_preview(db, event_id, actor_user_id) -> dict`
- `GET /api/events/{id}/settlement-preview`
- Preview includes raw debts, net positions, recommended transfers, source participant IDs, original/recommended counts, and whether transfer count decreased.

- [ ] Write failing service and API tests for membership, confirmed-only sources, empty/already-simple events, cycle compression and response privacy.
- [ ] Implement server-only preview calculation from raw balances and explanations.
- [ ] Explain optimized edges through raw debts and net positions; do not claim direct receipt allocation for a newly introduced pair.
- [ ] Add response schemas and endpoint.
- [ ] Run focused service/API tests.
- [ ] Commit as `feat(settlement): add explainable event settlement preview`.

### Task 3: Persist snapshot-backed plans and approvals

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/services/settlements.py`
- Modify: `app/services/indexes.py`
- Modify: `app/routers/events.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_app_config.py`

**Interfaces:**
- `create_settlement_plan(db, event_id, actor_user_id, *, idempotency_key) -> dict`
- `get_settlement_plan(db, plan_id, actor_user_id) -> dict`
- `list_settlement_plans(db, event_id, actor_user_id, *, limit, offset) -> dict`
- `approve_settlement_plan(db, plan_id, actor_user_id) -> dict`
- `reject_settlement_plan(db, plan_id, actor_user_id, reason) -> dict`

- [ ] Write failing tests for canonical snapshot hashing, duplicate creation, stale plans, rejected plans, concurrent/repeated approval and net-zero intermediary approval.
- [ ] Persist immutable raw rows, net positions, recommended edges, required approvers and algorithm version; omit currency until the whole event money model supports it.
- [ ] Require every participant in the raw source graph to approve.
- [ ] Mark pending plans stale when balances or active membership differ before approval/execution.
- [ ] Use guarded updates so repeated approvals are idempotent and terminal states cannot regress.
- [ ] Expose create/list/get/approve/reject endpoints; creation requires `Idempotency-Key`.
- [ ] Run focused service/API tests.
- [ ] Commit as `feat(settlement): add snapshot plans and participant approvals`.

### Task 4: Materialize unique settlement payment requests

**Files:**
- Modify: `app/services/settlements.py`
- Modify: `app/services/payments.py`
- Modify: `app/services/indexes.py`
- Modify: `app/schemas.py`
- Modify: `app/routers/events.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_app_config.py`

**Interfaces:**
- `execute_settlement_plan(db, plan_id, actor_user_id, *, idempotency_key) -> dict`
- Internal payment helper accepts only a loaded approved plan and exact stored edge.
- Generated requests include `origin="settlement_plan"`, `settlement_plan_id`, and stable `settlement_edge_id`.

- [ ] Write failing tests for execution before approval, stale execution, unauthorized actor, partial retry, different actor/key retry, unique edge enforcement and audit provenance.
- [ ] Add unique sparse index on `(settlement_plan_id, settlement_edge_id)` in `payment_requests`.
- [ ] Add an internal server-issued request helper that validates the approved plan and stored edge rather than accepting client parties/amounts.
- [ ] Materialize each edge idempotently; use guarded resumable execution so partial failure cannot duplicate completed edges.
- [ ] Keep debtor `mark-paid` and receiver confirmation unchanged; no request is automatically marked paid.
- [ ] Derive plan progress from linked request/payment states.
- [ ] Run payment and settlement service/API tests.
- [ ] Commit as `feat(settlement): create unique approved payment requests`.

### Task 5: Contract and safety documentation

**Files:**
- Modify: `openapi.yaml`
- Modify: `docs/wiki/API-Reference.md`
- Modify: `docs/wiki/Domain-Flows.md`
- Modify: `docs/wiki/Data-Model.md`
- Modify: `docs/p0-safety-flows.md`
- Modify: `tests/test_app_config.py`

- [ ] Add contract tests and regenerate `openapi.yaml` from `app.openapi()` using the repository’s established generator/check path.
- [ ] Document raw versus simplified balances, preview versus persisted plan, all-party approval, staleness and payment confirmation.
- [ ] Document that optimized pair explanations are based on net positions and source graph, not fictitious direct receipt ownership.
- [ ] Run OpenAPI and documentation contract tests.
- [ ] Commit as `docs(settlement): document safe debt simplification`.

### Task 6: Backend-served PWA settlement flow

**Files:**
- Modify the active files under `web/src/app` identified by current event/balance rendering.
- Modify or create focused contracts under `web/tests`.

- [ ] Load the required UI/UX and frontend implementation skills before editing UI files.
- [ ] Write failing UI contract tests for preview, empty/already-simple state, approval progress, stale/rejected state, payment-request state and errors.
- [ ] Add “Упростить расчёты” to the event balance surface.
- [ ] Show raw debt count versus recommended transfers, net positions and a plain-language explanation.
- [ ] Keep “Согласиться с планом” visually and semantically separate from “Я оплатил”.
- [ ] Show required approvals, current user action, stale refresh, and each generated payment request’s status.
- [ ] Verify narrow and wide layouts in the running app with screenshots.
- [ ] Commit as `feat(pwa): add event settlement plan experience`.

### Task 7: Full verification and branch review

- [ ] Run focused settlement tests and verify TDD regressions.
- [ ] Run `make test`, `make lint`, and `make format-check`.
- [ ] Verify `app.openapi()` matches `openapi.yaml`.
- [ ] Run frontend tests/build and browser smoke checks.
- [ ] Review the full branch diff for authorization, money conservation, concurrency/idempotency, privacy and unrelated changes.
- [ ] Fix all critical/important findings and repeat affected verification.
- [ ] Prepare a concise report with commits, tests and out-of-scope iOS follow-up.

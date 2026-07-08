# SplitAppBackend Full Repository Audit - 2026-07-09

Scope: `/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend` only.

This is a practical single-agent repository audit covering code, dependencies, documentation, CI/deploy, PWA, and security-sensitive flows. It is not a formal exhaustive Codex Security scan: the Codex Security preflight reported incomplete/degraded coverage without delegated workers.

## Executive Summary

The backend is in a relatively healthy state: backend tests, lint, format, OpenAPI sync, Python dependency audit, PWA contract tests, frontend lint, frontend build, and post-build typecheck all pass. The largest risks are not broken API behavior, but stale PWA legacy files, stale backlog/docs wording, one current Node advisory through Next's bundled PostCSS, token storage/XSS posture in the PWA, and missing maximum-length validation on several user-controlled write fields.

Top remediation order:

1. Fix the `npm audit` finding by upgrading Next/lockfile in a controlled PWA dependency update.
2. Remove or fully retire the old vanilla PWA fallback (`web/index.html`, `web/sw.js`, `web/assets/*`) or make FastAPI fail clearly when `web/out` is missing.
3. Add Pydantic length bounds for write payload strings and regression tests.
4. Decide whether PWA token storage in `localStorage` is acceptable for production; if not, design httpOnly-cookie/session flow or add CSP/hardening as an interim mitigation.
5. Update stale docs/backlog around systemd, decimal money wording, iOS secure storage wording, and production setup.

## Verified Checks

- `make test`: 179 passed, 1 skipped, 7 warnings.
- `make lint`: passed.
- `make format-check`: passed.
- `make security-audit`: passed, no known Python vulnerabilities.
- `node --test web/tests/pwa-ui-contract.test.mjs && node --test web/tests/pwa-cache-contract.test.mjs`: 64 tests passed.
- `npm run lint` in `web/`: passed.
- `npm run build` in `web/`: passed.
- `npm run typecheck` after build in `web/`: passed.
- `app.openapi()` vs `openapi.yaml`: equal, 72 paths, no missing or stale paths.
- `npm audit --omit=dev --audit-level=moderate`: failed with 2 moderate advisories via `next` bundled `postcss <8.5.10`.

## Confirmed Strengths

- Global `/api/*` authentication is enforced in `app/main.py` with explicit unauthenticated exceptions in `app/dependencies.py`.
- `/api/metrics` is token-protected and returns 404 on missing/invalid metrics token.
- Internal DB health route is hidden from public clients unless the request comes from loopback/private/link-local clients.
- Money-changing service functions consistently re-check actor/event membership server-side.
- Sensitive deletes are generally soft deletes or state transitions, not hard deletes.
- Receipt image replacement deletes the previous S3 object and uses presigned read URLs.
- OpenAPI is currently synchronized with the live FastAPI app.
- Docker Compose is the active production path, with MongoDB/Prometheus/Loki isolated inside the Compose network and Grafana bound to localhost by default.

## Findings

### P1 - Node production dependency audit fails

`npm audit --omit=dev --audit-level=moderate` reports `postcss <8.5.10` through `next@15.5.20`. The top-level `postcss` is already resolved to a safe version, but Next bundles `postcss@8.4.31`.

Evidence:

- `web/package.json` depends on `next` with `^15.5.0`.
- `npm ls next postcss` shows `next@15.5.20 -> postcss@8.4.31`.
- `npm audit` reports GHSA-qx2v-qp2m-jg93.

Recommendation: update Next and related lockfile carefully, then run `npm audit --omit=dev`, `npm run lint`, `npm run build`, `npm run typecheck`, and PWA contract tests. Do not use `npm audit fix --force` blindly because it proposed a breaking downgrade path.

### P1 - Old vanilla PWA fallback is still tracked

The current PWA is Next.js under `web/src` and `web/public`, but old fallback files remain tracked:

- `web/index.html`
- `web/sw.js`
- `web/manifest.webmanifest`
- `web/assets/*`

`app/main.py` falls back to `WEB_ROOT` if `web/out/index.html` is missing. That means a local or bad deploy without `web/out` can serve the old app shell and the old service worker cache `splitapp-pwa-v7`, while the current service worker is `splitapp-next-pwa-v33`.

Recommendation: either remove the old vanilla fallback and require `web/out`, or move fallback assets under an explicitly named demo/smoke path that cannot be confused with production PWA behavior.

### P1 - PWA stores bearer and refresh tokens in localStorage

`web/src/lib/splitapp-api.ts` stores `splitapp.tokens` in `window.localStorage`. This is simple and works for a PWA, but it makes refresh tokens directly reachable by any XSS or injected third-party script.

Recommendation: for production, prefer httpOnly secure cookies or a backend-managed session/token exchange. If that is too large for now, add a short-term hardening issue for CSP, no inline script policy, dependency hygiene, and explicit token lifetime/rotation review.

### P2 - Several write payload strings lack max length constraints

Some schemas have good bounds, but several user-controlled fields are unbounded at the Pydantic layer:

- `UserUpdate.name`, `email`, `avatar_url`, `payment_phone`
- `EventCreate.name`, `EventUpdate.name`
- `CreateReceiptItemRequest.name`
- `CreateReceiptRequest.title`
- `UpdateReceiptRequest.title`
- `PaymentRequestCreate.note`
- `DisputeResolve.resolution_note`
- `ReceiptShareReviewDispute.reason` has `min_length` but no `max_length`

Recommendation: add explicit max lengths in `app/schemas.py`, preserve service-level trim/normalization, and add regression tests for oversized write payloads.

### P2 - Typecheck command depends on generated `.next/types`

`npm run typecheck` fails before `npm run build` when `.next/types` is missing because `web/tsconfig.json` includes `.next/types/**/*.ts`. It passes after `next build` regenerates those files.

Recommendation: either document `build -> typecheck` ordering in CI/docs, or adjust the typecheck setup so a clean checkout can run `npm run typecheck` independently.

### P2 - Test suite uses an intentionally short JWT secret

Backend tests pass, but PyJWT emits `InsecureKeyLengthWarning` because `tests/conftest.py` sets `JWT_SECRET=test-secret`.

Recommendation: replace it with a 32+ byte test secret to keep warnings meaningful.

### P2 - Docs and backlog contain stale deployment and money wording

Examples:

- `TODO.md` still says README/server-runbook describe systemd and the next production step is systemd, while current README/CI now prefer Docker Compose.
- `docs/wiki/Domain-Flows.md` still documents balance amount as decimal money value.
- `docs/wiki/iOS-Frontend-Integration.md` still says money values should be decoded decimal-safe, while current backend contract is integer kopecks for new API values.

Recommendation: update `TODO.md` and affected wiki pages, or archive old planning documents that are no longer operational source of truth.

### P2 - `DESIGN.md` appears unrelated to SplitApp

`DESIGN.md` is a large Passionfroot style reference, not SplitApp-specific. It is tracked and may confuse future UI work.

Recommendation: remove it if unused, or move it under an explicitly named references/archive folder with a note that it is not the active SplitApp design system.

### P2 - `mongodb.py` compatibility shim may be obsolete

`mongodb.py` only re-exports from `app.core.db`. It may exist for old imports, but no current tracked code appears to need it.

Recommendation: check external scripts/deploy history. If no external import depends on it, remove it with a small regression/import check.

### P3 - Local generated artifacts clutter the working tree

Local untracked/generated artifacts exist:

- `output/`
- `.DS_Store`
- `.coverage`
- `pwa-preview.log`
- `uvicorn.log`
- `.pytest_cache/`
- `.ruff_cache/`
- `web/out/`
- `web/.next/`
- `web/tsconfig.tsbuildinfo`

Most are already ignored and not tracked. `docs/.DS_Store` appears under docs and should be deleted locally.

Recommendation: clean local generated artifacts before commits; keep `.gitignore` and `.dockerignore` aligned for generated PWA output and logs.

### P3 - Docs/public artifacts need ownership decisions

Several docs artifacts are useful for presentation/demo, but not clearly separated from durable engineering docs:

- `docs/business-logic-site/*`
- `docs/personal-contribution-module.html`
- `docs/presentation-assets/*`
- `docs/landing-content-checklist.md`
- `docs/pwa-app-design-checklist.md`
- `docs/diagrams/*`
- `docs/superpowers/plans/*`
- `docs/superpowers/specs/*`

Recommendation: keep `docs/wiki/*`, `README.md`, `openapi.yaml`, security/runbook docs as canonical. Move presentation/demo artifacts under `docs/archive/` or `docs/presentation/`, and decide whether Superpowers plans/specs are durable history or should be archived after implementation.

## Security Review Notes

No direct authz bypass was found in the sampled high-risk service paths. The backend generally avoids trusting client-supplied user ids for writes and re-checks actor membership close to service operations.

Areas that still deserve a dedicated deep security pass:

- PWA token storage and CSP/XSS posture.
- Upload validation beyond magic bytes/content type, especially Splitik attachments where content type allows PNG/WebP but bytes are not validated.
- Production exposure of `/api/metrics`, Grafana, Prometheus, Loki, and host exporters.
- Shell quoting in GitHub Actions deploy. Current deploy relies on repository secrets/vars; review with hostile secret values in mind before broadening maintainers.
- Rate limiter is in-memory only. It is fine for a single-process demo, but not strong enough for multi-replica production abuse controls.

## Dependency Review

Python:

- `requirements.txt` is pinned.
- `pip-audit` reports no known vulnerabilities.
- Runtime dependencies include test/tooling packages (`mongomock`, `pytest`, `ruff`, `pip-audit`) in the same production requirements file. This simplifies CI but bloats production images.

Node:

- `package-lock.json` exists and `npm ci` is used in Docker.
- `next`, `lucide-react`, `tailwind-merge`, Tailwind, ESLint, and TypeScript have newer majors/minors available.
- Only confirmed security issue is the Next/PostCSS advisory above.

Recommendation: split Python runtime and dev/test requirements when production image size/surface matters.

## Suggested Remediation Plan

1. `fix(pwa-deps): update Next dependency to clear PostCSS advisory`
   - Update package/lock.
   - Run Node audit and PWA gates.

2. `refactor(pwa): remove legacy vanilla shell fallback`
   - Remove or archive `web/index.html`, `web/sw.js`, `web/manifest.webmanifest`, `web/assets/*`.
   - Update `app/main.py`, README, and tests to require `web/out` or clearly expose a demo fallback.

3. `fix(api): bound write payload string lengths`
   - Add max lengths in `app/schemas.py`.
   - Add regression tests for oversized event/user/receipt/payment/dispute/client-facing strings.
   - Regenerate `openapi.yaml`.

4. `docs: refresh backend backlog and money/deploy wording`
   - Update `TODO.md`, `docs/wiki/Domain-Flows.md`, `docs/wiki/iOS-Frontend-Integration.md`, and any systemd-first wording that is now Compose-first.

5. `test(auth): use strong test JWT secret`
   - Replace `test-secret` fixture value with a 32+ byte test secret.
   - Confirm warnings drop.

6. `chore(docs): archive unrelated design and presentation artifacts`
   - Move/remove `DESIGN.md` if it is not active SplitApp guidance.
   - Group presentation outputs under a clear non-runtime docs folder.

## Out Of Scope

- iOS app fixes belong in `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.
- GitHub branch protection, environments, labels, and repository secrets require GitHub/production configuration, not only repo file edits.
- Production network exposure of observability services must be verified against the live host/reverse proxy.

# Full Repository Remediation - 2026-07-09

> Historical record. The PWA/Next runtime described below was removed on 2026-07-14 and replaced by a static public landing page plus the native iOS client.

## Fixed

- Updated PWA dependencies to a Next.js line that no longer bundles the vulnerable PostCSS version; `npm audit --omit=dev --audit-level=moderate` now reports zero vulnerabilities.
- Removed the legacy vanilla PWA shell and FastAPI fallback. The backend now serves only the generated Next.js export from `web/out`.
- Added server-side max-length bounds for user-controlled write strings and regenerated `openapi.yaml`.
- Added attachment content validation so declared image MIME types must match image magic bytes before local or object-storage persistence.
- Moved PWA bearer/refresh token persistence from permanent `localStorage` to tab-scoped `sessionStorage`.
- Updated frontend type generation so `npm run typecheck` works from a clean `.next` state.
- Removed obsolete tracked files: `DESIGN.md`, `mongodb.py`, and the old `web/assets/*` shell.
- Updated backend docs that still referenced old money-shape wording, legacy PWA fallback behavior, fixed Next bundle names, or systemd as the primary production path.
- Raised the test JWT secret length to avoid false-positive weak-key warnings during test runs.

## Verification

- `make test`
- `make lint`
- `make format-check`
- `make security-audit`
- `npm run lint`
- `npm run typecheck`
- `npm run build`
- `npm audit --omit=dev --audit-level=moderate`
- `npm ls next postcss`
- `node --test web/tests/pwa-ui-contract.test.mjs`
- `node --test web/tests/pwa-cache-contract.test.mjs`
- `git diff --check`
- `openapi.yaml` compared against `app.openapi()`

## Remaining Notes

- The token-storage change reduces persistent browser exposure, but a stronger production session model would be an httpOnly-cookie refresh flow plus CSP hardening.
- The frontend now uses `next@16.3.0-canary.80` because the latest stable Next release available during remediation still bundled the affected PostCSS dependency.
- Untracked/generated local artifacts were not bulk-deleted to avoid removing potentially user-owned report outputs.

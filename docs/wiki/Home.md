# SplitAppBackend Wiki

SplitAppBackend is the FastAPI backend for SplitApp. It owns authentication, users, events, receipts, debt calculation, payment confirmations, receipt images, operational monitoring, and the public API contract used by the iOS app.

## Quick Links

- [Project Overview](Project-Overview) - repository structure, runtime responsibilities, and main dependencies.
- [Local Setup](Local-Setup) - how to run the backend locally.
- [API Reference](API-Reference) - endpoint map and links to the OpenAPI contract.
- [Domain Flows](Domain-Flows) - how events, receipts, balances, and payments work together.
- [iOS Frontend Integration](iOS-Frontend-Integration) - backend contract used by the SplitApp iOS repository.
- [Authentication And Security](Authentication-And-Security) - auth model, authorization rules, storage rules, and baseline.
- [Operations And Deployment](Operations-And-Deployment) - production runtime, environment variables, systemd, logs, and metrics.
- [Testing And CI](Testing-And-CI) - tests, linting, GitHub Actions, and release checks.
- [Wiki Maintenance](Wiki-Maintenance) - how this Wiki is generated and synchronized.

## Repositories

- Backend: [Strongf-bob/SplitAppBackend](https://github.com/Strongf-bob/SplitAppBackend)
- iOS frontend: [Strongf-bob/SplitApp](https://github.com/Strongf-bob/SplitApp)
- Backend OpenAPI contract: [openapi.yaml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml)
- Backend README: [README.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/README.md)
- Security baseline: [docs/security-baseline.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/security-baseline.md)
- Remediation report: [docs/remediation-report.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/remediation-report.md)

## Current Backend Scope

The backend currently covers:

- Yandex OAuth token exchange and app token issuance.
- Refresh token rotation.
- Current-user profile updates.
- User listing limited to visible users.
- Event creation, listing, update, participant management, and delete.
- Receipt CRUD, item split shares, image upload, image deletion, and presigned image reads.
- Event balance calculation.
- Payment creation, listing, confirmation, and deletion.
- Explicit CORS, structured request logging, Prometheus metrics, and optional error reporting.
- Systemd-based production deployment path.

## Source Of Truth

The canonical API contract is `openapi.yaml`. When backend behavior changes, update these together in the same change:

- Python route/service/schema code.
- `openapi.yaml`.
- Tests.
- Wiki source pages under `docs/wiki/` when the behavior affects developer usage.


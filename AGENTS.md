# SplitAppBackend Agent Instructions

These instructions are mandatory for Codex work in this repository.

## Operating Rules
- Treat this repository as the backend scope only. If a task belongs to the iOS app, report it as follow-up work for `/Users/strongf/Developer/SplitApp Yandex/SplitApp`.
- Keep API behavior, `openapi.yaml`, tests, and docs in sync in the same change.
- Do not commit secrets, tokens, private keys, `.env`, production credentials, database dumps, or user data.
- Prefer narrow, reviewed changes with one security or behavior fix per commit.
- Use Conventional Commits for every commit.
- Run `make test` after backend behavior changes. Run `make lint` once lint tooling is available.

## Security Baseline
- Validate all write payloads on the server. Client validation is only UX.
- Never trust client-supplied user IDs without checking the authenticated actor and resource membership.
- Return generic client-facing errors for unexpected failures. Log full internal details on the server with request context.
- Keep CORS explicit: production origins and local development origins only.
- Keep authentication and authorization checks close to the service operation being protected.
- New list endpoints must define pagination before they are used by clients at scale.
- Storage operations must include delete/replacement behavior, not upload-only flows.
- Security-sensitive deletes must be soft deletes unless there is a documented reason to hard-delete.
- Add or update regression tests for every fixed vulnerability.

## Reporting
- End remediation work with a short report covering fixed backend issues, tests run, branches/commits created, and out-of-scope frontend items.
- If a requested issue is not in this backend repository, do not patch another repository unless explicitly requested. Record it in the report.

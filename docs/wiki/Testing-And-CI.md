# Testing And CI

## Local Test Commands

Run tests:

```bash
make test
```

Run lint:

```bash
make lint
```

Run format check:

```bash
make format-check
```

## Current CI

The backend CI workflow:

- Runs on pull requests.
- Runs on pushes to `main`.
- Runs on pushes to `strongf/**` branches.
- Installs Python dependencies.
- Runs Ruff.
- Runs pytest.
- Deploys only on push to `main`.

Workflow source:

- [.github/workflows/ci.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/ci.yml)

## Regression Testing Expectations

Add or update tests when changing:

- Authentication behavior.
- Authorization checks.
- Event membership rules.
- Receipt money logic.
- Payment sender or receiver permissions.
- Closed-event behavior.
- Storage deletion or replacement behavior.
- CORS, logging, or monitoring behavior.

## Backend Change Checklist

For behavior changes:

1. Update service or route code.
2. Update Pydantic schemas if payloads changed.
3. Update `openapi.yaml`.
4. Add or update tests.
5. Update Wiki source under `docs/wiki/` when developer usage changed.
6. Run `make test`.
7. Run `make lint` if lint tooling is available.

## Pull Request Review Focus

Reviewers should check:

- Does the authenticated actor control the operation?
- Does membership or creator authorization happen in the service layer?
- Are write payloads validated server-side?
- Do errors avoid leaking sensitive internal state?
- Does the OpenAPI contract match the code?
- Are frontend follow-ups documented when iOS behavior must change?


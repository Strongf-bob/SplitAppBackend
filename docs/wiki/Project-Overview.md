# Project Overview

## Purpose

SplitAppBackend provides the server-side API for splitting shared expenses. The iOS app should treat the backend as the source of truth for authenticated users, event membership, receipts, balances, payments, and receipt image storage.

## Runtime Stack

- FastAPI app entrypoint: [app/main.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/main.py)
- Compatibility entrypoint: [main.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/main.py)
- MongoDB connection and configuration: [app/core/db.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/db.py)
- S3-compatible receipt image storage: [app/core/s3.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/s3.py)
- JWT token helpers: [app/core/tokens.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/tokens.py)
- Monitoring hooks: [app/core/monitoring.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/core/monitoring.py)

## Application Layers

| Layer | Files | Responsibility |
| --- | --- | --- |
| App wiring | `app/main.py` | FastAPI creation, routers, CORS, logging middleware, exception handler, lifecycle setup. |
| Routers | `app/routers/*.py` | HTTP paths, request dependencies, response models. |
| Schemas | `app/schemas.py` | Pydantic request and response models. |
| Services | `app/services/*.py` | Business rules, authorization checks, persistence operations. |
| Core | `app/core/*.py` | Database, tokens, object storage, monitoring. |
| Tests | `tests/*.py` | Regression coverage for auth, event access, money, receipts, payments, config, and service behavior. |

## Router Map

- `app/routers/auth.py` - `/api/login`, `/api/refresh`.
- `app/routers/users.py` - `/api/users`, `/api/users/me`.
- `app/routers/events.py` - events, participants, balances.
- `app/routers/receipts.py` - receipts and receipt images.
- `app/routers/payments.py` - payments.
- `app/routers/health.py` - health and metrics.

## Main Data Concepts

| Concept | Meaning |
| --- | --- |
| User | Authenticated person known to the backend. |
| Event | Shared expense space. Users can see events only when they are creator or participant. |
| Receipt | Expense inside an event. Contains items and split shares. |
| Receipt item | One line in a receipt with cost and share assignments. |
| Share item | User-specific fraction of a receipt item. |
| Balance | Calculated debt edge from debtor to creditor for an event. |
| Payment | Declaration that one user paid another user inside an event. |

## Important Invariants

- Every protected endpoint depends on the authenticated actor.
- Client-supplied user IDs do not grant authorization by themselves.
- Event membership gates reads and financial operations.
- Event management is restricted to the event creator where required.
- Closed events block financial mutations.
- Receipt image storage is private; clients should use presigned URLs for temporary reads.
- Money calculations use decimal values, not floats.


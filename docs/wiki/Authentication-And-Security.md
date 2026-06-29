# Authentication And Security

## Authentication Model

The backend uses Yandex OAuth as the external identity provider:

1. iOS obtains a Yandex token.
2. iOS sends it to `POST /api/login`.
3. Backend validates the Yandex token and creates or finds the backend user.
4. Backend returns an app access token and refresh token.
5. Protected API calls use `Authorization: Bearer <access_token>`.
6. `POST /api/refresh` rotates the refresh token and returns a new access token.

## Authorization Baseline

Backend services must check the authenticated actor close to the operation being protected.

Rules:

- Never trust client-supplied user IDs without checking the authenticated actor.
- Event reads require creator or participant membership.
- Event management is creator-only where the operation changes event membership or event lifecycle.
- Payment creation requires authenticated actor to be the sender.
- Payment confirmation requires authenticated actor to be the receiver.
- Closed events reject financial mutations.
- User listing is visibility-limited, not a full user table dump.

## Storage Rules

- Receipt image objects should remain private.
- Clients should use presigned URLs for temporary reads.
- Replacements and deletes must clean up old storage state.
- Secrets belong in environment variables or managed secret stores.
- Do not commit `.env`, access keys, private keys, production credentials, database dumps, or user data.

## Error Handling

Client-facing unexpected failures should be generic:

```json
{
  "detail": "Internal server error."
}
```

Server logs should include request context such as:

- request ID
- method
- path
- status code
- duration
- internal exception type for unexpected failures

## CORS

Allowed origins should be explicit. Default development and production origins are configured in `app/main.py`, and production can override through `CORS_ALLOWED_ORIGINS`.

## Security Checklist Before Release

- Run `make test`.
- Run `make lint`.
- Confirm `openapi.yaml` matches route behavior.
- Confirm no secrets or user data are committed.
- Confirm production CORS origins are explicit.
- Confirm metrics exposure is protected by network or deployment policy.
- Confirm MongoDB and object storage encryption at rest.
- Confirm receipt images are private and read through presigned URLs.
- Review [docs/security-baseline.md](https://github.com/Strongf-bob/SplitAppBackend/blob/main/docs/security-baseline.md).


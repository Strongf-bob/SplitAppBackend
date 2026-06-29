# SplitApp Security Baseline

This checklist is the default security baseline for SplitApp backend work.

## Data And Legal Hygiene
- Keep a public privacy policy before collecting real user data.
- Know where user data is stored, including database region and third-party storage/services.
- Do not export user data into personal tools or store passwords/secrets in plaintext.
- Do not paste secrets, credentials, private user data, or production dumps into AI chats.

## Authentication And Authorization
- Verify sessions and authenticated actors in every API route.
- Never authorize access from a client-supplied user ID alone.
- Test negative auth flows, not only happy paths.
- Avoid responses that reveal whether a sensitive account identifier exists unless the product intentionally allows it.
- Refresh-token behavior must tolerate safe retries without creating permanent lockout after a lost response.

## API And Input Safety
- Validate all incoming write requests on the server: type, length, ranges, ownership, and membership.
- Use generic user-facing error messages for unexpected internal failures.
- Log internal exceptions on the server with request/correlation context.
- Rate-limit public and expensive endpoints before launch.
- Configure CORS with an explicit allowlist.
- Avoid over-fetching sensitive fields in API responses.

## Storage And Secrets
- Keep secret keys only in environment variables or managed secret stores.
- Public client keys are allowed only when they are designed to be public.
- Check Git history before launch for committed `.env` files or secrets.
- Object storage must support deletion/replacement and should avoid permanent public URLs where a presigned URL is more appropriate.
- Confirm encryption at rest for managed database and object storage.

## Operations
- Add structured logging before production usage.
- Add monitoring and alerting before relying on users to report failures.
- Prefer supervised deployment such as systemd or containers over `nohup`.
- Run lint, tests, and a security scan before release.
- Keep a remediation report for backend fixes and separately track frontend follow-up work.

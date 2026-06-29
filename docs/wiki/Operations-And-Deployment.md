# Operations And Deployment

## Production Runtime

Production deployment should use the systemd unit in:

- [deploy/splitapp-backend.service](https://github.com/Strongf-bob/SplitAppBackend/blob/main/deploy/splitapp-backend.service)

Recommended install path:

- `/opt/splitapp/backend`

Recommended env file:

- `/etc/splitapp/backend.env`

## Deploy Steps

```bash
sudo cp deploy/splitapp-backend.service /etc/systemd/system/splitapp-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now splitapp-backend
sudo systemctl status splitapp-backend
```

Logs:

```bash
journalctl -u splitapp-backend -f
```

## GitHub Actions Deployment

The main CI/CD workflow lives at:

- [.github/workflows/ci.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/ci.yml)

On push to `main`, it runs lint, tests, and then deploys through SSH when production secrets are configured.

Required deployment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH`
- Optional: `DEPLOY_PORT`

## Runtime Environment Variables

MongoDB:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- Or separate host/user/password/auth source values.
- TLS and replica set variables for managed clusters.

Object storage:

- `S3_ENDPOINT_URL`
- `S3_REGION`
- `S3_BUCKET`
- `YC_OBJECT_STORAGE_ACCESS_KEY_ID`
- `YC_OBJECT_STORAGE_SECRET_ACCESS_KEY`

Security and app behavior:

- JWT/access token settings used by token helpers.
- `CORS_ALLOWED_ORIGINS`
- Optional Sentry/error reporting configuration.

## Metrics

Prometheus metrics are exposed at:

- `GET /api/metrics`

If the backend is publicly reachable, protect metrics with deployment or network policy.

## Logs

The request middleware writes structured request completion logs with request ID, method, path, status, and duration. Unexpected exceptions are logged internally and returned to clients as generic errors.

## Operational Checks

- `GET /api/health/db` should confirm MongoDB connectivity.
- `GET /api/metrics` should return Prometheus text exposition.
- `systemctl status splitapp-backend` should be healthy after deploy.
- `journalctl -u splitapp-backend -f` should show request logs and startup failures.


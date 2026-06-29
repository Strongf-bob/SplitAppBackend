# Операции и деплой

## Production runtime

Production deployment должен использовать systemd unit:

- [deploy/splitapp-backend.service](https://github.com/Strongf-bob/SplitAppBackend/blob/main/deploy/splitapp-backend.service)

Recommended install path:

- `/opt/splitapp/backend`

Recommended env file:

- `/etc/splitapp/backend.env`

## Deploy steps

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

## GitHub Actions deployment

Основной CI/CD workflow:

- [.github/workflows/ci.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/ci.yml)

На push в `main` workflow запускает lint, tests и затем deploy over SSH, если настроены production secrets.

Required deployment secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH`
- Optional: `DEPLOY_PORT`

## Runtime environment variables

MongoDB:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- или отдельные host/user/password/auth source values.
- TLS и replica set variables для managed clusters.

Object storage:

- `S3_ENDPOINT_URL`
- `S3_REGION`
- `S3_BUCKET`
- `YC_OBJECT_STORAGE_ACCESS_KEY_ID`
- `YC_OBJECT_STORAGE_SECRET_ACCESS_KEY`

Security и app behavior:

- JWT/access token settings, используемые token helpers.
- `CORS_ALLOWED_ORIGINS`
- Optional Sentry/error reporting configuration.

## Metrics

Prometheus metrics:

- `GET /api/metrics`

Если backend публично доступен, metrics нужно закрыть deployment или network policy.

## Logs

Request middleware пишет structured request completion logs с request ID, method, path, status и duration. Unexpected exceptions логируются внутри сервера и возвращаются клиентам как generic errors.

## Operational checks

- `GET /api/health/db` должен подтверждать MongoDB connectivity.
- `GET /api/metrics` должен возвращать Prometheus text exposition.
- `systemctl status splitapp-backend` должен быть healthy после deploy.
- `journalctl -u splitapp-backend -f` должен показывать request logs и startup failures.


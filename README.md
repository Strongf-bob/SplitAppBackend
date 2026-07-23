<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="SplitApp Backend — authenticated APIs for receipts, balances, settlements, payments, and Splitik">
</p>

FastAPI backend нативного SplitApp: auth, события, друзья, чеки, платежи,
балансы, урегулирование долгов, Splitik-agent, S3-вложения и observability.
API-контракт зафиксирован в [`openapi.yaml`](openapi.yaml).

## Быстрый локальный запуск

```bash
make setup
cp .env.example .env
make run-dev
```

Заполните `.env` настройками MongoDB перед запуском. Проверка:

- login: `POST /api/login`;
- database health: `GET /api/health/db`;
- публичная продуктовая страница: `GET /`.

## MongoDB configuration

Поддерживаются три режима.

   Вариант A, полный connection string:

   `MONGODB_URI=mongodb://username:password@localhost:27017/?authSource=admin`

   Вариант B, отдельные значения:

   `MONGODB_HOST=localhost`

   `MONGODB_PORT=27017`

   `MONGODB_USER=username`

   `MONGODB_PASSWORD=password`

   `MONGODB_AUTH_SOURCE=admin`

   `MONGODB_DB_NAME=splitapp`

   Вариант C, managed cluster с replica set и TLS:

   `MONGODB_HOSTS=rc1b-4ukf7rtvtpealt1c.mdb.yandexcloud.net:27018`

   `MONGODB_USER=split-app`

   `MONGODB_PASSWORD=<your-password>`

   `MONGODB_DB_NAME=split-app`

   `MONGODB_AUTH_SOURCE=split-app`

   `MONGODB_REPLICA_SET=rs01`

   `MONGODB_TLS=true`

   `MONGODB_TLS_CA_FILE=/home/<your-home>/.mongodb/root.crt`

Публичный `GET /` отдает статичную страницу о нативном iOS-приложении SplitApp.
Она не требует Node.js-сборки. Все продуктовые данные и действия доступны
только через защищенный backend API `/api/*` с bearer auth.

## Запуск на сервере

### Docker Compose

Backend можно запускать как изолированный Docker Compose project с private
MongoDB, Prometheus и Loki. На host публикуются API port, localhost-bound
Grafana port и, если задан `GRAFANA_PUBLIC_DOMAIN`, public HTTPS proxy только
для Grafana.

1. `cp .env.docker.example .env`
2. Сгенерировать длинный случайный `JWT_SECRET` и обновить `.env`.
3. При необходимости изменить `HOST_PORT`, если `8080` занят.
4. Указать длинный `GRAFANA_ADMIN_PASSWORD`.
5. При необходимости изменить `GRAFANA_HOST_PORT`, если `3001` занят.
6. По умолчанию Grafana доступна через защищенный основной домен по адресу
   `https://split-app.ru/grafana/`; при другом домене задать
   `GRAFANA_PUBLIC_ROOT_URL=https://<domain>/grafana/`.
7. Для отдельного Grafana hostname указать `GRAFANA_PUBLIC_DOMAIN`, например
   `grafana.split-app.ru`, и направить DNS A/AAAA record на сервер. Если на host уже есть reverse proxy на `443`, оставить
   `GRAFANA_PUBLIC_PROXY_MODE=external` и проксировать домен на
   `127.0.0.1:${GRAFANA_HOST_PORT:-3001}`. Если Compose должен сам владеть
   `443`, поставить `GRAFANA_PUBLIC_PROXY_MODE=caddy` и запускать
   `COMPOSE_PROFILES=public-grafana docker compose up -d --build`.
8. `docker compose ps`

API слушает `http://<server-ip>:${HOST_PORT:-8080}`. MongoDB data хранится в
Docker volume `mongo-data` и не открывается наружу. Prometheus и Loki доступны
только внутри Compose network. Grafana по умолчанию bind'ится на
`127.0.0.1:${GRAFANA_HOST_PORT:-3001}`; используйте SSH tunnel или reverse proxy
с auth вместо публикации observability ports. Backend same-origin proxy
публикует только Grafana UI на `/grafana/`; вход остается через
`GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`, а Prometheus, Loki и
`/api/metrics` наружу не открываются. Отдельный hostname остается опциональным.

Перед сменой портов на общем сервере проверьте listeners:

`ss -ltnp | grep -E ':(${HOST_PORT:-8080}|${GRAFANA_HOST_PORT:-3001}|443)'`

Receipt image endpoints требуют S3 settings в `.env`; без них эти endpoints
вернут configuration error, но остальной API остается рабочим.

GitHub Actions deploy использует тот же Compose runtime на push в `main`.
Настройте repository secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`,
`DEPLOY_PATH`; production runtime secrets и Grafana credentials держите в
server-side `.env`.

### Systemd

Для production предпочтительнее Compose runtime выше. Systemd unit
`deploy/splitapp-backend.service` остается поддерживаемым вариантом для ручного
деплоя: приложение устанавливается в `/opt/splitapp/backend`, переменные среды
кладутся в `/etc/splitapp/backend.env`.

1. `sudo cp deploy/splitapp-backend.service /etc/systemd/system/splitapp-backend.service`
2. `sudo systemctl daemon-reload`
3. `sudo systemctl enable --now splitapp-backend`
4. `sudo systemctl status splitapp-backend`

Логи:

`journalctl -u splitapp-backend -f`

Legacy Make target можно использовать для быстрых ручных проверок:

1. `make setup`
2. `make run`

Defaults:

- Host: `0.0.0.0`
- Port: `8000`

Переопределить port/host:

`PORT=8080 HOST=0.0.0.0 make run`

Команды процесса:

- `make status`
- `make logs`
- `make stop`

MongoDB settings можно передать inline:

`MONGODB_URI="mongodb://username:password@localhost:27017/?authSource=admin" MONGODB_DB_NAME="splitapp" make run`

## Ручные venv-команды

1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `uvicorn main:app --host 0.0.0.0 --port 8000`

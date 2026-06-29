# Локальный запуск

## Требования

- Python 3.
- Доступная MongoDB.
- `.env` с MongoDB-настройками.
- Optional S3-compatible object storage variables, если нужно тестировать загрузку изображений чеков на реальном storage.

## Установка зависимостей

```bash
make setup
```

Команда создает `.venv` и ставит зависимости из `requirements.txt`.

## Environment

Создать локальный env-файл:

```bash
cp .env.example .env
```

Дальше заполнить MongoDB-настройки.

### Вариант A: полный MongoDB URI

```env
MONGODB_URI=mongodb://username:password@localhost:27017/?authSource=admin
MONGODB_DB_NAME=splitapp
```

### Вариант B: отдельные MongoDB значения

```env
MONGODB_HOST=localhost
MONGODB_PORT=27017
MONGODB_USER=username
MONGODB_PASSWORD=password
MONGODB_AUTH_SOURCE=admin
MONGODB_DB_NAME=splitapp
```

### Вариант C: managed MongoDB с TLS

```env
MONGODB_HOSTS=rc1b-4ukf7rtvtpealt1c.mdb.yandexcloud.net:27018
MONGODB_USER=split-app
MONGODB_PASSWORD=<your-password>
MONGODB_DB_NAME=split-app
MONGODB_AUTH_SOURCE=split-app
MONGODB_REPLICA_SET=rs01
MONGODB_TLS=true
MONGODB_TLS_CA_FILE=/home/<your-home>/.mongodb/root.crt
```

## Запуск dev-сервера

```bash
make run-dev
```

Default URL:

- `http://localhost:8000`

Полезные endpoints:

- `POST /api/login`
- `GET /api/health/db`
- `GET /api/metrics`

## Ручной запуск без Makefile

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Background-запуск для быстрых проверок

```bash
make run
make status
make logs
make stop
```

Переопределить host/port:

```bash
PORT=8080 HOST=0.0.0.0 make run
```

## Подключение iOS к локальному backend

iOS-клиент сейчас использует `https://splitapp.tech` в `APIClient`. Для локальной backend-разработки frontend-репозиторию нужен development base URL switch, чтобы не менять production URL руками в коде. Подробнее: [Интеграция с iOS](iOS-Frontend-Integration).


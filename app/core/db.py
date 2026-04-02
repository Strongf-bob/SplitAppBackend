import os
from pathlib import Path
from urllib.parse import quote_plus, urlencode

from fastapi import FastAPI
from pymongo import MongoClient
from pymongo.database import Database


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def build_mongodb_uri() -> str:
    mongodb_uri = os.getenv("MONGODB_URI")
    if mongodb_uri:
        return mongodb_uri

    mongodb_host = os.getenv("MONGODB_HOST", "localhost")
    mongodb_port = os.getenv("MONGODB_PORT", "27017")
    mongodb_hosts = os.getenv("MONGODB_HOSTS", "").strip()
    mongodb_user = os.getenv("MONGODB_USER")
    mongodb_password = os.getenv("MONGODB_PASSWORD")
    mongodb_db_name = os.getenv("MONGODB_DB_NAME", "splitapp")
    mongodb_auth_source = os.getenv("MONGODB_AUTH_SOURCE", mongodb_db_name)
    mongodb_replica_set = os.getenv("MONGODB_REPLICA_SET", "").strip()

    if bool(mongodb_user) != bool(mongodb_password):
        raise ValueError("Set both MONGODB_USER and MONGODB_PASSWORD, or neither.")

    if mongodb_hosts:
        hosts = ",".join(
            host.strip() for host in mongodb_hosts.split(",") if host.strip()
        )
    else:
        hosts = f"{mongodb_host}:{mongodb_port}"

    query: dict[str, str] = {"authSource": mongodb_auth_source}
    if mongodb_replica_set:
        query["replicaSet"] = mongodb_replica_set

    query_string = urlencode(query)
    if mongodb_user and mongodb_password:
        user = quote_plus(mongodb_user)
        password = quote_plus(mongodb_password)
        return f"mongodb://{user}:{password}@{hosts}/?{query_string}"

    return f"mongodb://{hosts}/?{query_string}"


def connect_mongodb(app: FastAPI) -> None:
    mongodb_uri = build_mongodb_uri()
    mongodb_tls_raw = os.getenv("MONGODB_TLS")
    mongodb_tls_ca_file = os.getenv("MONGODB_TLS_CA_FILE", "").strip()
    mongodb_replica_set = os.getenv("MONGODB_REPLICA_SET", "").strip()
    mongodb_hosts = os.getenv("MONGODB_HOSTS", "").strip()

    if mongodb_tls_raw is None:
        mongodb_tls = bool(mongodb_replica_set or mongodb_hosts)
    else:
        mongodb_tls = mongodb_tls_raw.lower() == "true"

    if mongodb_tls_ca_file and not mongodb_tls:
        mongodb_tls = True

    client_kwargs: dict[str, object] = {"serverSelectionTimeoutMS": 5000}
    if mongodb_tls:
        client_kwargs["tls"] = True
    if mongodb_tls_ca_file:
        client_kwargs["tlsCAFile"] = mongodb_tls_ca_file

    mongo_client = MongoClient(mongodb_uri, **client_kwargs)
    mongo_client.admin.command("ping")

    mongodb_db_name = os.getenv("MONGODB_DB_NAME", "splitapp")
    app.state.mongo_client = mongo_client
    app.state.db = mongo_client[mongodb_db_name]


def close_mongodb(app: FastAPI) -> None:
    app.state.mongo_client.close()


def get_db(app: FastAPI) -> Database:
    return app.state.db


def ping_mongodb(app: FastAPI) -> None:
    get_db(app).command("ping")


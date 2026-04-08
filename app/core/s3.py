import os
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from fastapi import FastAPI

_DEFAULT_ENDPOINT = "https://storage.yandexcloud.net"
_DEFAULT_REGION = "ru-central1"


def build_s3_client(
    *,
    endpoint_url: str | None = None,
    region_name: str | None = None,
) -> Any:
    """Return an S3-compatible client (e.g. Yandex Object Storage)."""
    endpoint = (
        endpoint_url
        if endpoint_url is not None
        else (os.getenv("S3_ENDPOINT_URL", _DEFAULT_ENDPOINT).strip() or _DEFAULT_ENDPOINT)
    )
    region = (
        region_name
        if region_name is not None
        else (os.getenv("S3_REGION", _DEFAULT_REGION).strip() or _DEFAULT_REGION)
    )

    key_id = os.getenv("YC_OBJECT_STORAGE_ACCESS_KEY_ID", "").strip()
    secret = os.getenv("YC_OBJECT_STORAGE_SECRET_ACCESS_KEY", "").strip()

    session = boto3.session.Session()
    client_kwargs: dict[str, Any] = {
        "service_name": "s3",
        "endpoint_url": endpoint,
        "region_name": region,
    }
    if key_id and secret:
        client_kwargs["aws_access_key_id"] = key_id
        client_kwargs["aws_secret_access_key"] = secret

    return session.client(**client_kwargs)


def connect_s3(app: "FastAPI") -> None:
    app.state.s3_client = build_s3_client()


def get_s3_client(app: "FastAPI") -> Any:
    return app.state.s3_client

from datetime import UTC, datetime
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


def strip_mongo_id(document: dict) -> dict:
    cleaned = dict(document)
    cleaned.pop("_id", None)
    return cleaned

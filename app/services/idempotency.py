import hashlib
import json
from collections.abc import Callable

from fastapi import HTTPException
from pymongo.database import Database

from app.services.common import new_uuid, utc_now


def _request_hash(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def run_idempotent_create(
    db: Database,
    *,
    actor_user_id: str,
    scope: str,
    key: str | None,
    request_payload: object,
    create: Callable[[], dict],
) -> dict:
    if not key:
        return create()

    request_hash = _request_hash(request_payload)
    query = {"actor_user_id": actor_user_id, "scope": scope, "key": key}
    existing = db.idempotency_keys.find_one(query)
    if existing:
        if existing["request_hash"] != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used with a different request.",
            )
        return dict(existing["response_snapshot"])

    response = create()
    now = utc_now()
    db.idempotency_keys.insert_one(
        {
            "id": new_uuid(),
            "actor_user_id": actor_user_id,
            "scope": scope,
            "key": key,
            "request_hash": request_hash,
            "response_snapshot": response,
            "status": "completed",
            "created_at": now,
            "updated_at": now,
        }
    )
    stored = db.idempotency_keys.find_one(query)
    return dict(stored["response_snapshot"])

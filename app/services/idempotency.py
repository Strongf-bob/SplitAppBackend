import hashlib
import json
from collections.abc import Callable

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from pymongo.database import Database

from app.services.common import new_uuid, utc_now


def _request_hash(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _response_from_existing(existing: dict, request_hash: str) -> dict:
    if existing["request_hash"] != request_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different request.",
        )
    if existing.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key request is still in progress.",
        )
    return dict(existing["response_snapshot"])


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
        return _response_from_existing(existing, request_hash)

    now = utc_now()
    reservation = {
        "id": new_uuid(),
        "actor_user_id": actor_user_id,
        "scope": scope,
        "key": key,
        "request_hash": request_hash,
        "status": "in_progress",
        "created_at": now,
        "updated_at": now,
    }
    try:
        db.idempotency_keys.insert_one(reservation)
    except DuplicateKeyError:
        existing = db.idempotency_keys.find_one(query)
        if existing:
            return _response_from_existing(existing, request_hash)
        raise

    try:
        response = create()
    except Exception:
        db.idempotency_keys.delete_one({**query, "request_hash": request_hash, "status": "in_progress"})
        raise

    db.idempotency_keys.update_one(
        {**query, "request_hash": request_hash, "status": "in_progress"},
        {
            "$set": {
                "response_snapshot": response,
                "status": "completed",
                "updated_at": utc_now(),
            }
        },
    )
    stored = db.idempotency_keys.find_one(query)
    return dict(stored["response_snapshot"])

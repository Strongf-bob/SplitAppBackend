from fastapi import HTTPException
from pymongo.database import Database
from datetime import timedelta

from app import schemas
from app.core.monitoring import observe_money_amount, record_domain_event, track_service_operation

from app.services.access import assert_event_access, assert_event_open, get_payment_or_404
from app.services.common import active_filter, new_uuid, record_audit_event, strip_mongo_id, utc_now
from app.services.common import money_to_storage, stored_money_to_kopecks
from app.services.idempotency import run_idempotent_create

_MIN_PAYMENT_REQUEST_DEADLINE = timedelta(minutes=30)


def _payment_to_api(payment: dict) -> dict:
    cleaned = strip_mongo_id(payment)
    cleaned["amount_kopecks"] = stored_money_to_kopecks(cleaned, "amount_kopecks", "amount")
    cleaned["status"] = cleaned.get("status", "confirmed" if cleaned.get("confirmed") else "pending")
    cleaned.pop("amount", None)
    return cleaned


def _payment_request_to_api(payment_request: dict) -> dict:
    cleaned = strip_mongo_id(payment_request)
    cleaned["amount_kopecks"] = stored_money_to_kopecks(cleaned, "amount_kopecks", "amount")
    cleaned.pop("amount", None)
    return cleaned


def _get_payment_request_or_404(db: Database, payment_request_id: str) -> dict:
    payment_request = db.payment_requests.find_one(active_filter({"id": payment_request_id}))
    if not payment_request:
        raise HTTPException(status_code=404, detail="Payment request not found.")
    return payment_request


def _assert_payment_request_party(payment_request: dict, actor_user_id: str) -> None:
    if actor_user_id not in {payment_request["debtor_id"], payment_request["creditor_id"]}:
        raise HTTPException(status_code=403, detail="Not a party to this payment request.")


@track_service_operation("payments.create")
def create_payment(
    db: Database,
    event_id: str,
    payload: schemas.PaymentCreate,
    actor_user_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"events:{event_id}:payments",
        key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create=lambda: _create_payment(db, event_id, payload, actor_user_id),
    )


def _create_payment(
    db: Database, event_id: str, payload: schemas.PaymentCreate, actor_user_id: str
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)
    sender_id = str(payload.sender_id)
    receiver_id = str(payload.receiver_id)

    if sender_id != actor_user_id:
        raise HTTPException(status_code=403, detail="sender_id must match the authenticated user.")

    if sender_id == receiver_id:
        raise HTTPException(status_code=400, detail="sender_id and receiver_id must differ.")

    if sender_id not in event["users"] or receiver_id not in event["users"]:
        raise HTTPException(
            status_code=400,
            detail="sender_id and receiver_id must belong to event users.",
        )

    payment = {
        "id": new_uuid(),
        "event_id": event_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount_kopecks": money_to_storage(payload.amount_kopecks),
        "status": "pending",
        "confirmed": False,
        "created_at": utc_now(),
    }
    db.payments.insert_one(payment)
    record_domain_event("payments", "created")
    record_audit_event(
        db,
        action="payment.created",
        resource_type="payment",
        resource_id=payment["id"],
        actor_user_id=actor_user_id,
    )
    observe_money_amount("payment_amount", payload.amount_kopecks / 100)
    return _payment_to_api(payment)


@track_service_operation("payments.list")
def list_payments_by_event(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    query = active_filter({"event_id": event_id})
    total = db.payments.count_documents(query)
    cursor = db.payments.find(query).sort("created_at", -1).skip(offset).limit(limit)
    return {
        "items": [_payment_to_api(item) for item in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("payments.update")
def update_payment(
    db: Database, payment_id: str, payload: schemas.PaymentUpdate, actor_user_id: str
) -> dict:
    payment = get_payment_or_404(db, payment_id)
    event = assert_event_access(db, payment["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment["receiver_id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the payment receiver can update confirmation.",
        )
    if payment.get("confirmed") and not payload.confirmed:
        raise HTTPException(status_code=409, detail="Confirmed payments cannot be unconfirmed.")
    status = "confirmed" if payload.confirmed else "pending"
    db.payments.update_one(
        {"id": payment_id},
        {"$set": {"confirmed": payload.confirmed, "status": status, "updated_at": utc_now()}},
    )
    record_domain_event("payments", "confirmed" if payload.confirmed else "unconfirmed")
    record_audit_event(
        db,
        action="payment.confirmation_updated",
        resource_type="payment",
        resource_id=payment_id,
        actor_user_id=actor_user_id,
    )
    return _payment_to_api(get_payment_or_404(db, payment_id))


@track_service_operation("payments.confirm")
def confirm_payment(db: Database, payment_id: str, actor_user_id: str) -> dict:
    payment = get_payment_or_404(db, payment_id)
    event = assert_event_access(db, payment["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment["receiver_id"]:
        raise HTTPException(status_code=403, detail="Only the payment receiver can confirm.")

    now = utc_now()
    update_fields = {
        "confirmed": True,
        "status": "confirmed",
        "confirmed_at": now,
        "updated_at": now,
    }
    db.payments.update_one({"id": payment_id}, {"$set": update_fields})
    if payment.get("payment_request_id"):
        db.payment_requests.update_one(
            {"id": payment["payment_request_id"]},
            {"$set": {"status": "confirmed", "updated_at": now}},
        )
    record_domain_event("payments", "confirmed")
    record_audit_event(
        db,
        action="payment.confirmed",
        resource_type="payment",
        resource_id=payment_id,
        actor_user_id=actor_user_id,
    )
    return _payment_to_api(get_payment_or_404(db, payment_id))


@track_service_operation("payments.reject")
def reject_payment(db: Database, payment_id: str, actor_user_id: str) -> dict:
    payment = get_payment_or_404(db, payment_id)
    event = assert_event_access(db, payment["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment["receiver_id"]:
        raise HTTPException(status_code=403, detail="Only the payment receiver can reject.")
    if payment.get("confirmed"):
        raise HTTPException(status_code=409, detail="Confirmed payments cannot be rejected.")

    now = utc_now()
    db.payments.update_one(
        {"id": payment_id},
        {
            "$set": {
                "confirmed": False,
                "status": "rejected",
                "rejected_at": now,
                "updated_at": now,
            }
        },
    )
    if payment.get("payment_request_id"):
        db.payment_requests.update_one(
            {"id": payment["payment_request_id"]},
            {"$set": {"status": "rejected", "updated_at": now}},
        )
    record_domain_event("payments", "rejected")
    record_audit_event(
        db,
        action="payment.rejected",
        resource_type="payment",
        resource_id=payment_id,
        actor_user_id=actor_user_id,
    )
    return _payment_to_api(get_payment_or_404(db, payment_id))


@track_service_operation("payments.delete")
def delete_payment(db: Database, payment_id: str, actor_user_id: str) -> None:
    payment = get_payment_or_404(db, payment_id)
    event = assert_event_access(db, payment["event_id"], actor_user_id)
    assert_event_open(event)

    if payment.get("confirmed"):
        raise HTTPException(status_code=409, detail="Confirmed payments cannot be deleted.")

    if actor_user_id not in {payment["sender_id"], payment["receiver_id"]}:
        raise HTTPException(
            status_code=403,
            detail="Only the payment sender or receiver can delete this payment.",
        )

    now = utc_now()
    db.payments.update_one(
        active_filter({"id": payment_id}),
        {"$set": {"deleted_at": now, "deleted_by": actor_user_id, "updated_at": now}},
    )
    record_domain_event("payments", "deleted")
    record_audit_event(
        db,
        action="payment.deleted",
        resource_type="payment",
        resource_id=payment_id,
        actor_user_id=actor_user_id,
    )


@track_service_operation("payment_requests.create")
def create_payment_request(
    db: Database,
    event_id: str,
    payload: schemas.PaymentRequestCreate,
    actor_user_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"events:{event_id}:payment_requests",
        key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create=lambda: _create_payment_request(db, event_id, payload, actor_user_id),
    )


def _create_payment_request(
    db: Database,
    event_id: str,
    payload: schemas.PaymentRequestCreate,
    actor_user_id: str,
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)
    debtor_id = str(payload.debtor_id)
    creditor_id = str(payload.creditor_id)

    if creditor_id != actor_user_id:
        raise HTTPException(status_code=403, detail="creditor_id must match the authenticated user.")
    if debtor_id == creditor_id:
        raise HTTPException(status_code=400, detail="debtor_id and creditor_id must differ.")
    if debtor_id not in event["users"] or creditor_id not in event["users"]:
        raise HTTPException(
            status_code=400,
            detail="debtor_id and creditor_id must belong to event users.",
        )

    now = utc_now()
    if payload.deadline_at is not None:
        deadline_at = payload.deadline_at
        if deadline_at.tzinfo is None:
            raise HTTPException(status_code=400, detail="deadline_at must include timezone.")
        if deadline_at < now + _MIN_PAYMENT_REQUEST_DEADLINE:
            raise HTTPException(status_code=400, detail="deadline_at must be at least 30 minutes out.")
    else:
        deadline_at = None

    payment_request = {
        "id": new_uuid(),
        "event_id": event_id,
        "debtor_id": debtor_id,
        "creditor_id": creditor_id,
        "amount_kopecks": money_to_storage(payload.amount_kopecks),
        "note": payload.note,
        "status": "requested",
        "created_by": actor_user_id,
        "deadline_at": deadline_at,
        "created_at": now,
        "updated_at": now,
    }
    db.payment_requests.insert_one(payment_request)
    record_domain_event("payment_requests", "created")
    record_audit_event(
        db,
        action="payment_request.created",
        resource_type="payment_request",
        resource_id=payment_request["id"],
        actor_user_id=actor_user_id,
    )
    observe_money_amount("payment_request_amount", payload.amount_kopecks / 100)
    return _payment_request_to_api(payment_request)


@track_service_operation("payment_requests.list")
def list_payment_requests_by_event(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    query = active_filter({"event_id": event_id})
    total = db.payment_requests.count_documents(query)
    cursor = db.payment_requests.find(query).sort("created_at", -1).skip(offset).limit(limit)
    return {
        "items": [_payment_request_to_api(item) for item in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("payment_requests.mark_paid")
def mark_payment_request_paid(
    db: Database,
    payment_request_id: str,
    actor_user_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"payment_requests:{payment_request_id}:mark_paid",
        key=idempotency_key,
        request_payload={"payment_request_id": payment_request_id},
        create=lambda: _mark_payment_request_paid(db, payment_request_id, actor_user_id),
    )


def _mark_payment_request_paid(
    db: Database, payment_request_id: str, actor_user_id: str
) -> dict:
    payment_request = _get_payment_request_or_404(db, payment_request_id)
    event = assert_event_access(db, payment_request["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment_request["debtor_id"]:
        raise HTTPException(status_code=403, detail="Only the debtor can mark this request paid.")
    if payment_request["status"] != "requested":
        raise HTTPException(status_code=409, detail="Payment request is not payable.")

    now = utc_now()
    payment = {
        "id": new_uuid(),
        "event_id": payment_request["event_id"],
        "sender_id": payment_request["debtor_id"],
        "receiver_id": payment_request["creditor_id"],
        "amount_kopecks": payment_request["amount_kopecks"],
        "status": "pending",
        "confirmed": False,
        "payment_request_id": payment_request_id,
        "created_at": now,
        "updated_at": now,
    }
    db.payments.insert_one(payment)
    db.payment_requests.update_one(
        {"id": payment_request_id},
        {"$set": {"status": "paid", "payment_id": payment["id"], "updated_at": now}},
    )
    record_domain_event("payment_requests", "marked_paid")
    record_domain_event("payments", "created")
    record_audit_event(
        db,
        action="payment_request.marked_paid",
        resource_type="payment_request",
        resource_id=payment_request_id,
        actor_user_id=actor_user_id,
    )
    record_audit_event(
        db,
        action="payment.created",
        resource_type="payment",
        resource_id=payment["id"],
        actor_user_id=actor_user_id,
    )
    return _payment_to_api(payment)


@track_service_operation("payment_requests.acknowledge")
def acknowledge_payment_request(
    db: Database, payment_request_id: str, actor_user_id: str
) -> dict:
    payment_request = _get_payment_request_or_404(db, payment_request_id)
    event = assert_event_access(db, payment_request["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment_request["debtor_id"]:
        raise HTTPException(status_code=403, detail="Only the debtor can acknowledge.")
    if payment_request["status"] != "requested":
        raise HTTPException(status_code=409, detail="Payment request cannot be acknowledged.")

    now = utc_now()
    db.payment_requests.update_one(
        {"id": payment_request_id},
        {"$set": {"acknowledged_at": now, "updated_at": now}},
    )
    record_domain_event("payment_requests", "acknowledged")
    record_audit_event(
        db,
        action="payment_request.acknowledged",
        resource_type="payment_request",
        resource_id=payment_request_id,
        actor_user_id=actor_user_id,
    )
    return _payment_request_to_api(_get_payment_request_or_404(db, payment_request_id))


@track_service_operation("payment_requests.cancel")
def cancel_payment_request(db: Database, payment_request_id: str, actor_user_id: str) -> dict:
    payment_request = _get_payment_request_or_404(db, payment_request_id)
    event = assert_event_access(db, payment_request["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment_request["creditor_id"]:
        raise HTTPException(status_code=403, detail="Only the creditor can cancel.")
    if payment_request["status"] not in {"requested", "paid", "rejected", "disputed"}:
        raise HTTPException(status_code=409, detail="Payment request cannot be cancelled.")

    now = utc_now()
    db.payment_requests.update_one(
        {"id": payment_request_id},
        {"$set": {"status": "cancelled", "cancelled_at": now, "updated_at": now}},
    )
    record_domain_event("payment_requests", "cancelled")
    record_audit_event(
        db,
        action="payment_request.cancelled",
        resource_type="payment_request",
        resource_id=payment_request_id,
        actor_user_id=actor_user_id,
    )
    return _payment_request_to_api(_get_payment_request_or_404(db, payment_request_id))


@track_service_operation("payment_requests.extension_requested")
def request_payment_extension(
    db: Database, payment_request_id: str, actor_user_id: str
) -> dict:
    payment_request = _get_payment_request_or_404(db, payment_request_id)
    event = assert_event_access(db, payment_request["event_id"], actor_user_id)
    assert_event_open(event)
    if actor_user_id != payment_request["debtor_id"]:
        raise HTTPException(status_code=403, detail="Only the debtor can request extension.")
    if payment_request["status"] != "requested":
        raise HTTPException(status_code=409, detail="Payment request is not active.")

    now = utc_now()
    db.payment_requests.update_one(
        {"id": payment_request_id},
        {"$set": {"extension_requested_at": now, "updated_at": now}},
    )
    record_domain_event("payment_requests", "extension_requested")
    record_audit_event(
        db,
        action="payment_request.extension_requested",
        resource_type="payment_request",
        resource_id=payment_request_id,
        actor_user_id=actor_user_id,
    )
    return _payment_request_to_api(_get_payment_request_or_404(db, payment_request_id))


@track_service_operation("payment_requests.dispute")
def dispute_payment_request(db: Database, payment_request_id: str, actor_user_id: str) -> dict:
    payment_request = _get_payment_request_or_404(db, payment_request_id)
    event = assert_event_access(db, payment_request["event_id"], actor_user_id)
    assert_event_open(event)
    _assert_payment_request_party(payment_request, actor_user_id)
    if payment_request["status"] not in {"requested", "paid", "rejected"}:
        raise HTTPException(status_code=409, detail="Payment request cannot be disputed.")

    now = utc_now()
    db.payment_requests.update_one(
        {"id": payment_request_id},
        {"$set": {"status": "disputed", "disputed_at": now, "updated_at": now}},
    )
    record_domain_event("payment_requests", "disputed")
    record_audit_event(
        db,
        action="payment_request.disputed",
        resource_type="payment_request",
        resource_id=payment_request_id,
        actor_user_id=actor_user_id,
    )
    return _payment_request_to_api(_get_payment_request_or_404(db, payment_request_id))


def get_payment_confirm_confirmation_summary(
    db: Database, payment_id: str, actor_user_id: str
) -> dict:
    payment = get_payment_or_404(db, payment_id)
    assert_event_access(db, payment["event_id"], actor_user_id)
    return {
        "resource_type": "payment",
        "resource_id": payment_id,
        "action": "confirm",
        "title": "Payment",
        "amount_kopecks": stored_money_to_kopecks(payment, "amount_kopecks", "amount"),
        "status": payment.get("status", "confirmed" if payment.get("confirmed") else "pending"),
        "actor_user_id": actor_user_id,
        "requires_explicit_confirmation": True,
        "warnings": ["Confirmed payments reduce outstanding balances."],
    }


def get_payment_reject_confirmation_summary(
    db: Database, payment_id: str, actor_user_id: str
) -> dict:
    payment = get_payment_or_404(db, payment_id)
    assert_event_access(db, payment["event_id"], actor_user_id)
    return {
        "resource_type": "payment",
        "resource_id": payment_id,
        "action": "reject",
        "title": "Payment",
        "amount_kopecks": stored_money_to_kopecks(payment, "amount_kopecks", "amount"),
        "status": payment.get("status", "confirmed" if payment.get("confirmed") else "pending"),
        "actor_user_id": actor_user_id,
        "requires_explicit_confirmation": True,
        "warnings": ["Rejected payments do not reduce outstanding balances."],
    }

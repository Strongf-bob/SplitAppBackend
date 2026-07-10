import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from pymongo.database import Database

from app.core.monitoring import record_domain_event, track_service_operation
from app.services.access import (
    active_event_user_ids,
    assert_event_access,
    assert_event_open,
)
from app.services.balances import (
    _get_event_balance_explanations_unchecked,
    get_event_balance_explanations,
)
from app.services.common import new_uuid, record_audit_event, strip_mongo_id, utc_now
from app.services.idempotency import run_idempotent_create
from app.services.settlement_algorithm import build_settlement_edges

ALGORITHM_VERSION = "greedy-net-v1"
PENDING_PLAN_TTL = timedelta(hours=24)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _source_participant_ids(raw_debts: list[dict]) -> list[str]:
    participant_ids = {
        user_id for row in raw_debts for user_id in (row["debitor_id"], row["creditor_id"])
    }
    return sorted(participant_ids)


def _net_positions(raw_debts: list[dict]) -> list[dict]:
    positions: dict[str, int] = {}
    for row in raw_debts:
        amount_kopecks = row["amount_kopecks"]
        debtor_id = row["debitor_id"]
        creditor_id = row["creditor_id"]
        positions[debtor_id] = positions.get(debtor_id, 0) - amount_kopecks
        positions[creditor_id] = positions.get(creditor_id, 0) + amount_kopecks

    debtors: list[dict[str, str | int | Literal["owes", "receives"]]] = [
        {"user_id": user_id, "direction": "owes", "amount_kopecks": -amount}
        for user_id, amount in positions.items()
        if amount < 0
    ]
    creditors: list[dict[str, str | int | Literal["owes", "receives"]]] = [
        {"user_id": user_id, "direction": "receives", "amount_kopecks": amount}
        for user_id, amount in positions.items()
        if amount > 0
    ]

    debtors.sort(key=lambda item: (-int(item["amount_kopecks"]), str(item["user_id"])))
    creditors.sort(key=lambda item: (-int(item["amount_kopecks"]), str(item["user_id"])))
    return debtors + creditors


def _sorted_contributions(contributions: list[dict]) -> list[dict]:
    return sorted(
        (dict(item) for item in contributions),
        key=lambda item: (
            str(item.get("source_type", "")),
            str(item.get("source_id", "")),
            str(item.get("debitor_id", "")),
            str(item.get("creditor_id", "")),
            int(item.get("amount_kopecks", 0)),
            str(item.get("description", "")),
        ),
    )


def _canonical_preview(preview: dict) -> dict:
    raw_debts = []
    for row in preview["raw_debts"]:
        canonical = dict(row)
        canonical["contributions"] = _sorted_contributions(row.get("contributions", []))
        raw_debts.append(canonical)
    raw_debts.sort(
        key=lambda row: (
            str(row["debitor_id"]),
            str(row["creditor_id"]),
            int(row["amount_kopecks"]),
            json.dumps(row["contributions"], sort_keys=True, separators=(",", ":")),
        )
    )

    net_positions = sorted(
        (dict(item) for item in preview["net_positions"]),
        key=lambda item: (
            str(item["direction"]),
            -int(item["amount_kopecks"]),
            str(item["user_id"]),
        ),
    )
    recommended_transfers = sorted(
        (dict(item) for item in preview["recommended_transfers"]),
        key=lambda item: (
            str(item["debtor_id"]),
            str(item["creditor_id"]),
            int(item["amount_kopecks"]),
        ),
    )

    return {
        "event_id": preview["event_id"],
        "raw_debts": raw_debts,
        "net_positions": net_positions,
        "recommended_transfers": recommended_transfers,
        "source_participant_ids": sorted(preview["source_participant_ids"]),
        "original_transfer_count": int(preview["original_transfer_count"]),
        "recommended_transfer_count": int(preview["recommended_transfer_count"]),
        "original_gross_kopecks": int(preview["original_gross_kopecks"]),
        "recommended_total_kopecks": int(preview["recommended_total_kopecks"]),
        "transfer_count_reduced": bool(preview["transfer_count_reduced"]),
    }


def _snapshot_for_current_state(
    db: Database, event_id: str, actor_user_id: str
) -> tuple[dict, str]:
    preview = _canonical_preview(_get_settlement_preview_unchecked(db, event_id))
    snapshot = {
        "algorithm_version": ALGORITHM_VERSION,
        "preview": preview,
        "raw_debts": preview["raw_debts"],
        "net_positions": preview["net_positions"],
        "recommended_transfers": preview["recommended_transfers"],
        "active_membership_user_ids": sorted(active_event_user_ids(db, event_id)),
    }
    body = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return snapshot, hashlib.sha256(body.encode("utf-8")).hexdigest()


def _build_settlement_preview(event_id: str, raw_debts: list[dict]) -> dict:
    recommended_edges = build_settlement_edges(raw_debts)

    return {
        "event_id": event_id,
        "raw_debts": raw_debts,
        "net_positions": _net_positions(raw_debts),
        "recommended_transfers": [
            {
                "debtor_id": row["debitor_id"],
                "creditor_id": row["creditor_id"],
                "amount_kopecks": row["amount_kopecks"],
            }
            for row in recommended_edges
        ],
        "source_participant_ids": _source_participant_ids(raw_debts),
        "original_transfer_count": len(raw_debts),
        "recommended_transfer_count": len(recommended_edges),
        "original_gross_kopecks": sum(row["amount_kopecks"] for row in raw_debts),
        "recommended_total_kopecks": sum(row["amount_kopecks"] for row in recommended_edges),
        "transfer_count_reduced": len(recommended_edges) < len(raw_debts),
    }


def _get_settlement_preview_unchecked(db: Database, event_id: str) -> dict:
    raw_debts = _get_event_balance_explanations_unchecked(db, event_id)
    return _build_settlement_preview(event_id, raw_debts)


def _plan_to_api(plan: dict) -> dict:
    cleaned = strip_mongo_id(plan)
    preview = cleaned.get("preview") or cleaned.get("canonical_snapshot", {}).get("preview")
    approvals = sorted(
        (dict(item) for item in cleaned.get("approvals", [])),
        key=lambda item: str(item["user_id"]),
    )
    result = {
        "id": cleaned["id"],
        "event_id": cleaned["event_id"],
        "status": cleaned["status"],
        "algorithm_version": cleaned.get("algorithm_version", ALGORITHM_VERSION),
        "preview": preview,
        "required_approver_ids": sorted(cleaned.get("required_approver_ids", [])),
        "approvals": approvals,
        "created_by": cleaned["created_by"],
        "expires_at": cleaned["expires_at"],
        "created_at": cleaned["created_at"],
        "updated_at": cleaned["updated_at"],
    }
    if cleaned.get("rejected_by") is not None:
        result["rejected_by"] = cleaned["rejected_by"]
    if cleaned.get("rejection_reason") is not None:
        result["rejection_reason"] = cleaned["rejection_reason"]
    if cleaned.get("rejected_at") is not None:
        result["rejected_at"] = cleaned["rejected_at"]
    return result


def _get_plan_or_404(db: Database, plan_id: str) -> dict:
    plan = db.settlement_plans.find_one({"id": plan_id, "deleted_at": {"$exists": False}})
    if not plan:
        raise HTTPException(status_code=404, detail="Settlement plan not found.")
    return plan


def _record_plan_mutation(db: Database, plan_id: str, actor_user_id: str, action: str) -> None:
    record_domain_event("settlement_plans", action)
    record_audit_event(
        db,
        action=f"settlement_plan.{action}",
        resource_type="settlement_plan",
        resource_id=plan_id,
        actor_user_id=actor_user_id,
    )


def _transition_expired_if_needed(db: Database, plan: dict, actor_user_id: str) -> dict:
    if plan["status"] != "pending":
        return plan
    expires_at = _as_utc(plan["expires_at"])
    if expires_at > utc_now():
        return plan
    now = utc_now()
    result = db.settlement_plans.update_one(
        {"id": plan["id"], "status": "pending"},
        {
            "$set": {"status": "expired", "updated_at": now},
            "$unset": {"active_key": ""},
        },
    )
    if result.modified_count:
        _record_plan_mutation(db, plan["id"], actor_user_id, "expired")
    return _get_plan_or_404(db, plan["id"])


def _transition_stale(
    db: Database,
    *,
    plan_id: str,
    actor_user_id: str,
    action_id: str | None = None,
    statuses: set[str] | None = None,
) -> dict:
    query: dict = {"id": plan_id}
    if statuses is not None:
        query["status"] = {"$in": sorted(statuses)}
    if action_id is not None:
        query["last_action_id"] = action_id
    now = utc_now()
    result = db.settlement_plans.update_one(
        query,
        {
            "$set": {"status": "stale", "updated_at": now},
            "$unset": {
                "active_key": "",
                "rejected_by": "",
                "rejection_reason": "",
                "rejected_at": "",
            },
        },
    )
    if result.modified_count:
        _record_plan_mutation(db, plan_id, actor_user_id, "stale")
    return _get_plan_or_404(db, plan_id)


def _ensure_current_snapshot_or_mark_stale(
    db: Database,
    plan: dict,
    actor_user_id: str,
    *,
    action_id: str | None = None,
    statuses: set[str] | None = None,
) -> dict:
    if statuses is None and plan["status"] != "pending":
        return plan
    _, current_hash = _snapshot_for_current_state(db, plan["event_id"], actor_user_id)
    if current_hash == plan["snapshot_hash"]:
        return plan
    _transition_stale(
        db,
        plan_id=plan["id"],
        actor_user_id=actor_user_id,
        action_id=action_id,
        statuses=statuses or {"pending"},
    )
    raise HTTPException(status_code=409, detail="Settlement plan snapshot is stale.")


@track_service_operation("settlements.preview")
def get_settlement_preview(db: Database, event_id: str, actor_user_id: str) -> dict:
    raw_debts = get_event_balance_explanations(db, event_id, actor_user_id)
    return _build_settlement_preview(event_id, raw_debts)


@track_service_operation("settlement_plans.create")
def create_settlement_plan(
    db: Database, event_id: str, actor_user_id: str, *, idempotency_key: str
) -> dict:
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"events:{event_id}:settlement_plans",
        key=idempotency_key,
        request_payload={"event_id": event_id},
        create=lambda: _create_settlement_plan(db, event_id, actor_user_id),
    )


def _create_settlement_plan(db: Database, event_id: str, actor_user_id: str) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)
    snapshot, snapshot_hash = _snapshot_for_current_state(db, event_id, actor_user_id)
    preview = snapshot["preview"]
    if not preview["transfer_count_reduced"]:
        raise HTTPException(
            status_code=409,
            detail="Settlement plan can be created only when preview reduces transfers.",
        )

    active_key = f"{event_id}:{snapshot_hash}"
    if db.settlement_plans.find_one({"active_key": active_key}):
        raise HTTPException(
            status_code=409,
            detail="Active settlement plan already exists for this event snapshot.",
        )

    now = utc_now()
    plan = {
        "id": new_uuid(),
        "event_id": event_id,
        "status": "pending",
        "algorithm_version": ALGORITHM_VERSION,
        "preview": preview,
        "raw_debts": preview["raw_debts"],
        "net_positions": preview["net_positions"],
        "recommended_transfers": preview["recommended_transfers"],
        "required_approver_ids": preview["source_participant_ids"],
        "approvals": [],
        "created_by": actor_user_id,
        "expires_at": now + PENDING_PLAN_TTL,
        "created_at": now,
        "updated_at": now,
        "canonical_snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "active_key": active_key,
    }
    try:
        db.settlement_plans.insert_one(plan)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Active settlement plan already exists for this event snapshot.",
        ) from None
    _record_plan_mutation(db, plan["id"], actor_user_id, "created")
    return _plan_to_api(plan)


@track_service_operation("settlement_plans.get")
def get_settlement_plan(db: Database, plan_id: str, actor_user_id: str) -> dict:
    plan = _get_plan_or_404(db, plan_id)
    assert_event_access(db, plan["event_id"], actor_user_id)
    plan = _transition_expired_if_needed(db, plan, actor_user_id)
    return _plan_to_api(plan)


@track_service_operation("settlement_plans.list")
def list_settlement_plans(
    db: Database, event_id: str, actor_user_id: str, *, limit: int, offset: int
) -> dict:
    assert_event_access(db, event_id, actor_user_id)
    query = {"event_id": event_id, "deleted_at": {"$exists": False}}
    total = db.settlement_plans.count_documents(query)
    cursor = (
        db.settlement_plans.find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .skip(offset)
        .limit(limit)
    )
    items = [
        _plan_to_api(_transition_expired_if_needed(db, plan, actor_user_id)) for plan in cursor
    ]
    return {"items": items, "limit": limit, "offset": offset, "total": total}


def _ensure_required_approver(plan: dict, actor_user_id: str) -> None:
    if actor_user_id not in set(plan.get("required_approver_ids", [])):
        raise HTTPException(status_code=403, detail="Only required approvers can act on this plan.")


def _ensure_pending_for_action(plan: dict) -> None:
    if plan["status"] == "pending":
        return
    if plan["status"] == "approved":
        raise HTTPException(status_code=409, detail="Settlement plan is already approved.")
    raise HTTPException(status_code=409, detail="Settlement plan is no longer active.")


@track_service_operation("settlement_plans.approve")
def approve_settlement_plan(db: Database, plan_id: str, actor_user_id: str) -> dict:
    plan = _get_plan_or_404(db, plan_id)
    assert_event_access(db, plan["event_id"], actor_user_id)
    plan = _transition_expired_if_needed(db, plan, actor_user_id)
    if plan["status"] == "approved" and any(
        approval["user_id"] == actor_user_id for approval in plan.get("approvals", [])
    ):
        return _plan_to_api(plan)
    _ensure_pending_for_action(plan)
    plan = _ensure_current_snapshot_or_mark_stale(db, plan, actor_user_id)
    _ensure_required_approver(plan, actor_user_id)

    if any(approval["user_id"] == actor_user_id for approval in plan.get("approvals", [])):
        return _plan_to_api(plan)

    now = utc_now()
    action_id = new_uuid()
    result = db.settlement_plans.update_one(
        {"id": plan_id, "status": "pending", "approvals.user_id": {"$ne": actor_user_id}},
        {
            "$push": {"approvals": {"user_id": actor_user_id, "approved_at": now}},
            "$set": {"updated_at": now, "last_action_id": action_id},
        },
    )
    if result.matched_count == 0:
        current = _get_plan_or_404(db, plan_id)
        if any(approval["user_id"] == actor_user_id for approval in current.get("approvals", [])):
            return _plan_to_api(current)
        _ensure_pending_for_action(current)
        raise HTTPException(status_code=409, detail="Settlement approval could not be saved.")

    current = _get_plan_or_404(db, plan_id)
    approved_user_ids = {approval["user_id"] for approval in current.get("approvals", [])}
    required_user_ids = set(current["required_approver_ids"])
    promoted = False
    if required_user_ids.issubset(approved_user_ids):
        promoted_result = db.settlement_plans.update_one(
            {"id": plan_id, "status": "pending", "last_action_id": action_id},
            {"$set": {"status": "approved", "updated_at": utc_now(), "last_action_id": action_id}},
        )
        promoted = promoted_result.modified_count > 0
        current = _get_plan_or_404(db, plan_id)

    current = _ensure_current_snapshot_or_mark_stale(
        db,
        current,
        actor_user_id,
        action_id=action_id,
        statuses={"pending", "approved"},
    )
    _record_plan_mutation(db, plan_id, actor_user_id, "approval_created")
    if promoted:
        _record_plan_mutation(db, plan_id, actor_user_id, "approved")
    return _plan_to_api(current)


@track_service_operation("settlement_plans.reject")
def reject_settlement_plan(db: Database, plan_id: str, actor_user_id: str, reason: str) -> dict:
    plan = _get_plan_or_404(db, plan_id)
    assert_event_access(db, plan["event_id"], actor_user_id)
    plan = _transition_expired_if_needed(db, plan, actor_user_id)
    _ensure_pending_for_action(plan)
    plan = _ensure_current_snapshot_or_mark_stale(db, plan, actor_user_id)
    _ensure_required_approver(plan, actor_user_id)

    cleaned_reason = reason.strip()
    if not cleaned_reason or len(cleaned_reason) > 500:
        raise HTTPException(status_code=422, detail="Rejection reason must be 1-500 characters.")
    now = utc_now()
    action_id = new_uuid()
    result = db.settlement_plans.update_one(
        {"id": plan_id, "status": "pending"},
        {
            "$set": {
                "status": "rejected",
                "rejected_by": actor_user_id,
                "rejection_reason": cleaned_reason,
                "rejected_at": now,
                "updated_at": now,
                "last_action_id": action_id,
            },
            "$unset": {"active_key": ""},
        },
    )
    if result.matched_count == 0:
        current = _get_plan_or_404(db, plan_id)
        _ensure_pending_for_action(current)
        raise HTTPException(status_code=409, detail="Settlement rejection could not be saved.")

    current = _ensure_current_snapshot_or_mark_stale(
        db,
        _get_plan_or_404(db, plan_id),
        actor_user_id,
        action_id=action_id,
        statuses={"rejected"},
    )
    _record_plan_mutation(db, plan_id, actor_user_id, "rejected")
    return _plan_to_api(current)

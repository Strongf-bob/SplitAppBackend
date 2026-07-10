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
from app.services.common import active_filter
from app.services.idempotency import run_idempotent_create
import app.services.payments as payment_services
from app.services.settlement_algorithm import build_settlement_edges

ALGORITHM_VERSION = "greedy-net-v1"
PENDING_PLAN_TTL = timedelta(hours=24)
EXECUTION_REFRESH_STATUSES = {"executing", "partially_settled", "completed"}


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


def _edges_from_recommended_transfers(recommended_transfers: list[dict]) -> list[dict]:
    return [
        {
            "edge_id": new_uuid(),
            "debtor_id": transfer["debtor_id"],
            "creditor_id": transfer["creditor_id"],
            "amount_kopecks": transfer["amount_kopecks"],
        }
        for transfer in recommended_transfers
    ]


def _plan_edges_to_api(plan: dict) -> list[dict]:
    edges = []
    for edge in plan.get("edges", []):
        if not all(
            key in edge for key in ("edge_id", "debtor_id", "creditor_id", "amount_kopecks")
        ):
            continue
        cleaned_edge = {
            "edge_id": edge["edge_id"],
            "debtor_id": edge["debtor_id"],
            "creditor_id": edge["creditor_id"],
            "amount_kopecks": int(edge["amount_kopecks"]),
        }
        if edge.get("payment_request_id") is not None:
            cleaned_edge["payment_request_id"] = edge["payment_request_id"]
        if edge.get("status") is not None:
            cleaned_edge["status"] = edge["status"]
        edges.append(cleaned_edge)
    return edges


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
        "edges": _plan_edges_to_api(cleaned),
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


def _find_payment_request_for_edge(db: Database, plan_id: str, edge: dict) -> dict | None:
    if edge.get("payment_request_id"):
        payment_request = db.payment_requests.find_one(
            active_filter({"id": edge["payment_request_id"]})
        )
        if payment_request:
            return payment_request
    return db.payment_requests.find_one(
        active_filter(
            {
                "settlement_plan_id": plan_id,
                "settlement_edge_id": edge["edge_id"],
            }
        )
    )


def _derive_edge_progress(db: Database, plan: dict) -> tuple[list[dict], int, int]:
    refreshed_edges = []
    linked_count = 0
    confirmed_count = 0
    for edge in plan.get("edges", []):
        refreshed_edge = dict(edge)
        payment_request = _find_payment_request_for_edge(db, plan["id"], edge)
        if payment_request:
            linked_count += 1
            refreshed_edge["payment_request_id"] = payment_request["id"]
            refreshed_edge["status"] = payment_request["status"]
            if payment_request["status"] == "confirmed":
                confirmed_count += 1
        refreshed_edges.append(refreshed_edge)
    return refreshed_edges, linked_count, confirmed_count


def _desired_execution_status(
    plan: dict, *, edge_count: int, linked_count: int, confirmed_count: int
) -> str:
    if edge_count == 0 or linked_count == 0:
        return plan["status"]
    if confirmed_count == edge_count:
        return "completed"
    if confirmed_count > 0:
        return "partially_settled"
    return "executing"


def _refresh_plan_progress(db: Database, plan: dict, actor_user_id: str) -> dict:
    if plan["status"] not in EXECUTION_REFRESH_STATUSES:
        return plan
    edges = plan.get("edges", [])
    if not edges:
        return plan

    refreshed_edges, linked_count, confirmed_count = _derive_edge_progress(db, plan)
    desired_status = _desired_execution_status(
        plan,
        edge_count=len(refreshed_edges),
        linked_count=linked_count,
        confirmed_count=confirmed_count,
    )
    now = utc_now()
    if refreshed_edges != edges:
        db.settlement_plans.update_one(
            {"id": plan["id"]},
            {"$set": {"edges": refreshed_edges, "updated_at": now}},
        )
        plan = _get_plan_or_404(db, plan["id"])

    if desired_status != plan["status"]:
        result = db.settlement_plans.update_one(
            {"id": plan["id"], "status": plan["status"]},
            {"$set": {"status": desired_status, "updated_at": utc_now()}},
        )
        if result.modified_count:
            _record_plan_mutation(db, plan["id"], actor_user_id, desired_status)
        plan = _get_plan_or_404(db, plan["id"])
    return plan


def refresh_settlement_plan_progress_for_payment_request(
    db: Database, payment_request_id: str, actor_user_id: str
) -> dict | None:
    payment_request = db.payment_requests.find_one(active_filter({"id": payment_request_id}))
    if not payment_request or not payment_request.get("settlement_plan_id"):
        return None
    plan = _get_plan_or_404(db, payment_request["settlement_plan_id"])
    return _refresh_plan_progress(db, plan, actor_user_id)


def _create_or_get_settlement_payment_request(
    db: Database, plan_id: str, edge_id: str, actor_user_id: str
) -> dict:
    return payment_services.create_or_get_settlement_payment_request(
        db, plan_id=plan_id, edge_id=edge_id, actor_user_id=actor_user_id
    )


def _transition_approved_plan_to_executing(db: Database, plan: dict, actor_user_id: str) -> dict:
    action_id = new_uuid()
    result = db.settlement_plans.update_one(
        {"id": plan["id"], "status": "approved"},
        {"$set": {"status": "executing", "updated_at": utc_now(), "last_action_id": action_id}},
    )
    if result.modified_count:
        _record_plan_mutation(db, plan["id"], actor_user_id, "executing")
    current = _get_plan_or_404(db, plan["id"])
    if current["status"] in EXECUTION_REFRESH_STATUSES:
        return current
    if current["status"] == "approved":
        raise HTTPException(status_code=409, detail="Settlement execution could not be started.")
    raise HTTPException(status_code=409, detail="Settlement plan is no longer executable.")


def _link_edge_payment_request(
    db: Database, plan_id: str, edge_id: str, payment_request: dict
) -> None:
    db.settlement_plans.update_one(
        {"id": plan_id, "edges.edge_id": edge_id},
        {
            "$set": {
                "edges.$.payment_request_id": payment_request["id"],
                "edges.$.status": payment_request["status"],
                "updated_at": utc_now(),
            }
        },
    )


def _execute_settlement_plan(db: Database, plan_id: str, actor_user_id: str) -> dict:
    plan = _get_plan_or_404(db, plan_id)
    event = assert_event_access(db, plan["event_id"], actor_user_id)
    assert_event_open(event)

    plan = _refresh_plan_progress(db, plan, actor_user_id)
    if plan["status"] == "approved":
        plan = _ensure_current_snapshot_or_mark_stale(
            db, plan, actor_user_id, statuses={"approved"}
        )
        plan = _transition_approved_plan_to_executing(db, plan, actor_user_id)
        plan = _ensure_current_snapshot_or_mark_stale(
            db,
            plan,
            actor_user_id,
            action_id=plan.get("last_action_id"),
            statuses={"executing"},
        )
    elif plan["status"] not in EXECUTION_REFRESH_STATUSES:
        raise HTTPException(status_code=409, detail="Settlement plan is not approved.")

    for edge in plan.get("edges", []):
        payment_request = _find_payment_request_for_edge(db, plan["id"], edge)
        if payment_request is None:
            payment_request = _create_or_get_settlement_payment_request(
                db, plan["id"], edge["edge_id"], actor_user_id
            )
        _link_edge_payment_request(db, plan["id"], edge["edge_id"], payment_request)
        plan = _get_plan_or_404(db, plan["id"])

    plan = _refresh_plan_progress(db, plan, actor_user_id)
    return _plan_to_api(plan)


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
        "edges": _edges_from_recommended_transfers(preview["recommended_transfers"]),
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
    plan = _refresh_plan_progress(db, plan, actor_user_id)
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
    items = []
    for plan in cursor:
        plan = _transition_expired_if_needed(db, plan, actor_user_id)
        plan = _refresh_plan_progress(db, plan, actor_user_id)
        items.append(_plan_to_api(plan))
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@track_service_operation("settlement_plans.execute")
def execute_settlement_plan(
    db: Database, plan_id: str, actor_user_id: str, *, idempotency_key: str
) -> dict:
    plan = _get_plan_or_404(db, plan_id)
    event = assert_event_access(db, plan["event_id"], actor_user_id)
    assert_event_open(event)
    return run_idempotent_create(
        db,
        actor_user_id=actor_user_id,
        scope=f"settlement_plans:{plan_id}:execute",
        key=idempotency_key,
        request_payload={"plan_id": plan_id},
        create=lambda: _execute_settlement_plan(db, plan_id, actor_user_id),
    )


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

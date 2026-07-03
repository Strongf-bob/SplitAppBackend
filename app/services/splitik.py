from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.services import splitik_llm
from app.services.access import (
    active_event_memberships,
    assert_event_access,
    get_receipt_or_404,
    get_user_or_404,
)
from app.services.balances import get_event_balance_explanations, get_event_balances
from app.services.common import new_uuid, strip_mongo_id, utc_now, user_to_api_dict
from app.services.splitik_guardrails import evaluate_user_message
from app.services.splitik_interactions import log_interaction
from app.services import splitik_tools

_MODES = {"general", "event", "receipt", "member"}

_FORBIDDEN_CAPABILITIES = [
    "forbidden:impersonate_user",
    "forbidden:delete_event",
    "forbidden:edit_existing_money_state",
    "forbidden:mark_foreign_payment_paid",
]

_SYSTEM_PROMPT = """
You are Splitik, a SplitApp assistant. Answer in the user's language.
Use only the backend-provided context. Do not claim that you changed data unless
the backend response includes a committed resource. For changes, explain the
draft/confirmation step. Never ask for secrets, payment credentials, or private
data outside the provided SplitApp context.
""".strip()


def _clean(document: dict) -> dict:
    return strip_mongo_id(document)


def _draft_to_api(draft: dict) -> dict:
    return splitik_tools.draft_to_api(draft)


def _session_to_api(session: dict) -> dict:
    return _clean(session)


def _context_chip(chip_type: str, label: str, value: str) -> dict:
    return {"type": chip_type, "label": label, "value": value}


def _mode_capabilities(mode: str) -> list[str]:
    read_by_mode = {
        "general": ["read:user_summary", "read:event_summary", "read:friends"],
        "event": ["read:event_summary", "read:event_transactions", "read:balance_explanation"],
        "receipt": ["read:event_summary", "read:receipt_details", "read:balance_explanation"],
        "member": ["read:event_summary", "read:member_context", "read:balance_explanation"],
    }
    draft_by_mode = {
        "general": ["draft:create_event", "draft:add_receipt", "commit:create_event"],
        "event": ["draft:add_receipt"],
        "receipt": [],
        "member": [],
    }
    return read_by_mode[mode] + draft_by_mode[mode] + _FORBIDDEN_CAPABILITIES


def _event_summary(db: Database, event_id: str, actor_user_id: str) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    memberships = active_event_memberships(db, event_id)
    member_ids = [membership["user_id"] for membership in memberships]
    users = {
        user["id"]: user_to_api_dict(user) for user in db.users.find({"id": {"$in": member_ids}})
    }
    return {
        "event": _clean(event),
        "participants": [
            {
                "membership": _clean(membership),
                "user": users.get(membership["user_id"]),
            }
            for membership in memberships
        ],
    }


def _build_general_context(db: Database, actor_user_id: str) -> tuple[dict, list[dict]]:
    user = get_user_or_404(db, actor_user_id)
    memberships = list(
        db.event_memberships.find(
            {"user_id": actor_user_id, "status": "active", "deleted_at": {"$exists": False}}
        )
        .sort("joined_at", -1)
        .limit(10)
    )
    event_ids = [membership["event_id"] for membership in memberships]
    events = [_clean(event) for event in db.events.find({"id": {"$in": event_ids}}).limit(10)]
    friendships = [
        _clean(friendship)
        for friendship in db.friends.find(
            {
                "status": "accepted",
                "deleted_at": {"$exists": False},
                "$or": [{"requester_id": actor_user_id}, {"addressee_id": actor_user_id}],
            }
        )
        .sort("updated_at", -1)
        .limit(20)
    ]
    return (
        {"current_user": user_to_api_dict(user), "events": events, "friendships": friendships},
        [_context_chip("user", "Профиль", user["name"])],
    )


def _build_event_context(
    db: Database, event_id: str, actor_user_id: str
) -> tuple[dict, list[dict]]:
    summary = _event_summary(db, event_id, actor_user_id)
    receipts = [
        _clean(receipt)
        for receipt in db.receipts.find({"event_id": event_id, "deleted_at": {"$exists": False}})
        .sort("created_at", -1)
        .limit(20)
    ]
    balances = get_event_balances(db, event_id, actor_user_id)
    explanations = get_event_balance_explanations(db, event_id, actor_user_id)
    return (
        {
            **summary,
            "receipts": receipts,
            "balances": balances,
            "balance_explanations": explanations,
        },
        [_context_chip("event", "Событие", summary["event"]["name"])],
    )


def _build_receipt_context(
    db: Database, receipt_id: str, actor_user_id: str
) -> tuple[dict, list[dict]]:
    receipt = get_receipt_or_404(db, receipt_id)
    event_id = receipt["event_id"]
    summary = _event_summary(db, event_id, actor_user_id)
    items = [
        _clean(item)
        for item in db.receipt_items.find(
            {"receipt_id": receipt_id, "deleted_at": {"$exists": False}}
        ).sort("created_at", 1)
    ]
    share_items = [
        _clean(item)
        for item in db.share_items.find(
            {"receipt_item_id": {"$in": [item["id"] for item in items]}}
        )
    ]
    return (
        {**summary, "receipt": _clean(receipt), "receipt_items": items, "share_items": share_items},
        [
            _context_chip("event", "Событие", summary["event"]["name"]),
            _context_chip("receipt", "Расход", receipt.get("title") or receipt["id"]),
        ],
    )


def _build_member_context(
    db: Database, event_id: str, target_user_id: str, actor_user_id: str
) -> tuple[dict, list[dict]]:
    summary = _event_summary(db, event_id, actor_user_id)
    member_ids = {membership["membership"]["user_id"] for membership in summary["participants"]}
    if target_user_id not in member_ids:
        raise HTTPException(status_code=403, detail="Target user is not visible in this event.")
    target = get_user_or_404(db, target_user_id)
    receipts = [
        _clean(receipt)
        for receipt in db.receipts.find(
            {
                "event_id": event_id,
                "payer_id": target_user_id,
                "deleted_at": {"$exists": False},
            }
        )
        .sort("created_at", -1)
        .limit(20)
    ]
    balances = [
        row
        for row in get_event_balances(db, event_id, actor_user_id)
        if target_user_id in {row["debitor_id"], row["creditor_id"]}
    ]
    return (
        {
            **summary,
            "target_user": user_to_api_dict(target),
            "target_paid_receipts": receipts,
            "balances": balances,
        },
        [
            _context_chip("event", "Событие", summary["event"]["name"]),
            _context_chip("member", "Участник", target["name"]),
        ],
    )


def _build_context(
    db: Database, payload: schemas.SplitikMessageRequest, actor_user_id: str
) -> tuple[dict, list[dict], list[str]]:
    mode = payload.mode.strip().lower()
    if mode not in _MODES:
        raise HTTPException(status_code=400, detail="Invalid Splitik mode.")

    entry = payload.entry_point or schemas.SplitikEntryPoint(type=mode)
    if mode == "general":
        context, chips = _build_general_context(db, actor_user_id)
    elif mode == "event":
        if not entry.event_id:
            raise HTTPException(status_code=400, detail="event_id is required for event mode.")
        context, chips = _build_event_context(db, str(entry.event_id), actor_user_id)
    elif mode == "receipt":
        if not entry.receipt_id:
            raise HTTPException(status_code=400, detail="receipt_id is required for receipt mode.")
        context, chips = _build_receipt_context(db, str(entry.receipt_id), actor_user_id)
    else:
        if not entry.event_id or not entry.target_user_id:
            raise HTTPException(
                status_code=400, detail="event_id and target_user_id are required for member mode."
            )
        context, chips = _build_member_context(
            db, str(entry.event_id), str(entry.target_user_id), actor_user_id
        )

    context["splitik"] = {"mode": mode, "locale": payload.locale, "timezone": payload.timezone}
    return context, chips, _mode_capabilities(mode)


def _extract_event_name(message: str) -> str | None:
    normalized = " ".join(message.strip().split())
    lowered = normalized.casefold()
    if "событ" not in lowered and "event" not in lowered:
        return None
    for marker in ("создай событие", "create event", "событие:"):
        index = lowered.find(marker)
        if index >= 0:
            name = normalized[index + len(marker) :].strip(" :.-")
            if name:
                return name[:80]
    return None


def _maybe_create_draft(
    db: Database,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    session_id: str,
) -> list[dict]:
    mode = payload.mode.strip().lower()
    lowered = payload.message.casefold()
    if mode == "general":
        event_name = _extract_event_name(payload.message)
        if not event_name:
            return []
        return [
            splitik_tools.create_event_draft(
                db,
                actor_user_id=actor_user_id,
                session_id=session_id,
                payload={"name": event_name},
            )
        ]

    if mode != "event" or not payload.entry_point or not payload.entry_point.event_id:
        return []

    event_id = str(payload.entry_point.event_id)
    amount_kopecks = splitik_tools.amount_kopecks_from_text(payload.message)
    latest_receipt_draft = splitik_tools.latest_pending_draft(
        db,
        actor_user_id=actor_user_id,
        session_id=session_id,
        draft_type="create_receipt",
    )
    if (
        latest_receipt_draft
        and amount_kopecks
        and any(marker in lowered for marker in ("поменяй", "измени", "исправь", "сумм"))
    ):
        payload_patch = dict(latest_receipt_draft["payload"])
        payload_patch["total_amount_kopecks"] = amount_kopecks
        if payload_patch.get("items"):
            payload_patch["items"][0]["cost_kopecks"] = amount_kopecks
        return [
            splitik_tools.update_draft(
                db,
                actor_user_id=actor_user_id,
                draft_id=latest_receipt_draft["id"],
                patch={"payload": payload_patch},
            )
        ]

    if not any(marker in lowered for marker in ("чек", "счет", "счёт", "заплатил")):
        return []

    receipt_payload = splitik_tools.build_simple_receipt_payload(
        db,
        event_id=event_id,
        actor_user_id=actor_user_id,
        message=payload.message,
    )
    if not receipt_payload:
        return []
    return [
        splitik_tools.create_receipt_draft(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            event_id=event_id,
            payload=receipt_payload,
        )
    ]


def _get_or_create_session(
    db: Database, payload: schemas.SplitikMessageRequest, actor_user_id: str
) -> dict:
    now = utc_now()
    if payload.session_id:
        session = db.splitik_sessions.find_one(
            {"id": str(payload.session_id), "owner_user_id": actor_user_id}
        )
        if not session:
            raise HTTPException(status_code=404, detail="Splitik session not found.")
        return session

    session = {
        "id": new_uuid(),
        "owner_user_id": actor_user_id,
        "mode": payload.mode.strip().lower(),
        "locale": payload.locale,
        "timezone": payload.timezone,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    db.splitik_sessions.insert_one(session)
    return session


def send_splitik_message(
    db: Database, payload: schemas.SplitikMessageRequest, actor_user_id: str
) -> dict:
    get_user_or_404(db, actor_user_id)
    mode = payload.mode.strip().lower()
    guardrail_decision = evaluate_user_message(payload.message, context_scope=mode)
    if not guardrail_decision["allowed"]:
        session = _get_or_create_session(db, payload, actor_user_id)
        now = utc_now()
        message_id = new_uuid()
        reply = guardrail_decision["message"]
        db.splitik_sessions.update_one(
            {"id": session["id"]},
            {
                "$push": {
                    "messages": {
                        "id": message_id,
                        "user_message": payload.message,
                        "assistant_message": reply,
                        "mode": mode,
                        "created_at": now,
                    }
                },
                "$set": {"updated_at": now, "mode": mode},
            },
        )
        log_interaction(
            db,
            actor_user_id=actor_user_id,
            session_id=session["id"],
            message_id=message_id,
            sanitized_user_message=payload.message,
            intent="refusal",
            context_scope=mode,
            assistant_message=reply,
            guardrail_decision=guardrail_decision,
        )
        return {
            "session_id": session["id"],
            "message_id": message_id,
            "assistant_message": reply,
            "mode": mode,
            "intent": "refusal",
            "guardrail_decision": guardrail_decision,
            "context_chips": [],
            "capabilities": [],
            "drafts": [],
            "questions": [],
            "suggested_actions": [],
        }

    context, chips, capabilities = _build_context(db, payload, actor_user_id)
    session = _get_or_create_session(db, payload, actor_user_id)
    drafts = _maybe_create_draft(db, payload, actor_user_id, session["id"])
    if drafts:
        context["drafts"] = drafts

    reply = splitik_llm.generate_splitik_reply(
        system_prompt=_SYSTEM_PROMPT,
        user_message=payload.message,
        context=context,
    )
    now = utc_now()
    message_id = new_uuid()
    intent = "draft" if drafts else "chat"
    db.splitik_sessions.update_one(
        {"id": session["id"]},
        {
            "$push": {
                "messages": {
                    "id": message_id,
                    "user_message": payload.message,
                    "assistant_message": reply,
                    "mode": payload.mode.strip().lower(),
                    "created_at": now,
                }
            },
            "$set": {"updated_at": now, "mode": payload.mode.strip().lower()},
        },
    )
    log_interaction(
        db,
        actor_user_id=actor_user_id,
        session_id=session["id"],
        message_id=message_id,
        sanitized_user_message=payload.message,
        intent=intent,
        context_scope=payload.mode.strip().lower(),
        assistant_message=reply,
        guardrail_decision=guardrail_decision,
        draft_ids=[str(draft["id"]) for draft in drafts],
    )
    return {
        "session_id": session["id"],
        "message_id": message_id,
        "assistant_message": reply,
        "mode": payload.mode.strip().lower(),
        "intent": intent,
        "guardrail_decision": guardrail_decision,
        "context_chips": chips,
        "capabilities": capabilities,
        "drafts": drafts,
        "questions": [],
        "suggested_actions": [],
    }


def get_splitik_session(db: Database, session_id: str, actor_user_id: str) -> dict:
    session = db.splitik_sessions.find_one({"id": session_id, "owner_user_id": actor_user_id})
    if not session:
        raise HTTPException(status_code=404, detail="Splitik session not found.")
    return _session_to_api(session)


def get_splitik_draft(db: Database, draft_id: str, actor_user_id: str) -> dict:
    return splitik_tools.get_draft(db, actor_user_id=actor_user_id, draft_id=draft_id)


def update_splitik_draft(
    db: Database,
    draft_id: str,
    payload: schemas.SplitikDraftUpdateRequest,
    actor_user_id: str,
) -> dict:
    return splitik_tools.update_draft(
        db,
        actor_user_id=actor_user_id,
        draft_id=draft_id,
        patch=payload.model_dump(mode="json"),
    )


def commit_splitik_draft(db: Database, draft_id: str, actor_user_id: str) -> dict:
    return splitik_tools.commit_draft(db, actor_user_id=actor_user_id, draft_id=draft_id)

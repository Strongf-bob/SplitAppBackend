from fastapi import HTTPException
from pydantic import ValidationError
from pymongo.database import Database

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.services import splitik_llm
from app.services.access import active_event_memberships, assert_event_access, assert_event_open
from app.services.common import new_uuid, strip_mongo_id, utc_now, user_to_api_dict

_SYSTEM_PROMPT = """
You create SplitApp receipt drafts from user-provided receipt text.
Use only backend-provided event participants and payer constraints.
Return a JSON object with:
{
  "payload": {
    "payer_id": "uuid",
    "title": "string",
    "category": "string or null",
    "total_amount_kopecks": 1000,
    "items": [
      {
        "name": "string",
        "cost_kopecks": 1000,
        "split_mode": "custom",
        "share_items": [{"user_id": "uuid", "share_value": 1}]
      }
    ],
    "discount_amount_kopecks": 0,
    "service_fee_amount_kopecks": 0,
    "delivery_fee_amount_kopecks": 0,
    "tip_amount_kopecks": 0,
    "rounding_adjustment_kopecks": 0,
    "fiscal_total_amount_kopecks": null,
    "vat_amount_kopecks": null
  },
  "warnings": ["short human-review warning"]
}
Never create payments, never confirm receipts, and never claim that money was changed.
""".strip()


def _event_context(db: Database, event: dict, preferred_payer_id: str | None) -> dict:
    memberships = active_event_memberships(db, event["id"])
    member_ids = [membership["user_id"] for membership in memberships]
    users = [
        user_to_api_dict(user)
        for user in db.users.find({"id": {"$in": member_ids}})
    ]
    return {
        "event": strip_mongo_id(event),
        "memberships": [strip_mongo_id(membership) for membership in memberships],
        "participants": users,
        "preferred_payer_id": preferred_payer_id,
        "required_money_unit": "kopecks",
        "required_split_mode": "custom",
        "human_review_required": True,
    }


def _candidate_to_model_result(candidate: dict) -> dict:
    content = candidate.get("content", {})
    payload = content.get("payload") if isinstance(content, dict) else None
    warnings = content.get("warnings", []) if isinstance(content, dict) else []
    try:
        parsed_payload = schemas.CreateReceiptRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="Splitik receipt draft response was invalid.") from exc

    if not isinstance(warnings, list):
        warnings = ["Model returned warnings in an invalid shape."]
    return {
        "model_role": candidate["model_role"],
        "model_id": candidate["model_id"],
        "payload": parsed_payload.model_dump(mode="json"),
        "warnings": [str(warning) for warning in warnings],
    }


def _normalized_payload(payload: dict) -> dict:
    parsed = schemas.CreateReceiptRequest.model_validate(payload)
    return parsed.model_dump(mode="json")


def _compare_payloads(primary: dict, verification: dict) -> list[str]:
    disagreements: list[str] = []
    primary_payload = _normalized_payload(primary)
    verification_payload = _normalized_payload(verification)

    critical_fields = (
        "payer_id",
        "title",
        "category",
        "total_amount_kopecks",
        "discount_amount_kopecks",
        "service_fee_amount_kopecks",
        "delivery_fee_amount_kopecks",
        "tip_amount_kopecks",
        "rounding_adjustment_kopecks",
        "fiscal_total_amount_kopecks",
        "vat_amount_kopecks",
    )
    for field in critical_fields:
        if primary_payload.get(field) != verification_payload.get(field):
            disagreements.append(field)

    if primary_payload.get("items") != verification_payload.get("items"):
        disagreements.append("items")
    return disagreements


def _persisted_to_api(draft: dict) -> dict:
    cleaned = strip_mongo_id(draft)
    cleaned["draft_payload"] = schemas.CreateReceiptRequest.model_validate(
        cleaned["draft_payload"]
    ).model_dump(mode="json")
    return cleaned


@track_service_operation("receipt_ai_drafts.create")
def create_receipt_ai_draft(
    db: Database,
    event_id: str,
    payload: schemas.ReceiptAIDraftRequest,
    actor_user_id: str,
) -> dict:
    event = assert_event_access(db, event_id, actor_user_id)
    assert_event_open(event)

    preferred_payer_id = str(payload.payer_id) if payload.payer_id else actor_user_id
    if preferred_payer_id not in event["users"]:
        raise HTTPException(status_code=400, detail="payer_id must belong to event users.")

    context = _event_context(db, event, preferred_payer_id)
    context["splitik"] = {
        "locale": payload.locale,
        "timezone": payload.timezone,
        "model_policy": {
            "primary": "MiMo V2 5 Pro",
            "verification": "Qwen 3 7 Max",
            "escalation": "Kimi K2 5",
        },
    }

    primary_result = _candidate_to_model_result(
        splitik_llm.generate_receipt_draft_candidate(
            model_role="primary",
            system_prompt=_SYSTEM_PROMPT,
            user_message=payload.source_text,
            context=context,
        )
    )
    verification_result = _candidate_to_model_result(
        splitik_llm.generate_receipt_draft_candidate(
            model_role="verification",
            system_prompt=_SYSTEM_PROMPT,
            user_message=payload.source_text,
            context=context,
        )
    )
    disagreements = _compare_payloads(primary_result["payload"], verification_result["payload"])
    model_status = "matched"
    draft_payload = primary_result["payload"]
    escalation_result = None

    if disagreements:
        model_status = "escalated"
        escalation_context = {
            **context,
            "primary_payload": primary_result["payload"],
            "verification_payload": verification_result["payload"],
            "disagreements": disagreements,
        }
        escalation_result = _candidate_to_model_result(
            splitik_llm.generate_receipt_draft_candidate(
                model_role="escalation",
                system_prompt=_SYSTEM_PROMPT,
                user_message=payload.source_text,
                context=escalation_context,
            )
        )
        draft_payload = escalation_result["payload"]

    now = utc_now()
    draft = {
        "id": new_uuid(),
        "event_id": event_id,
        "owner_user_id": actor_user_id,
        "status": "pending_review",
        "model_status": model_status,
        "needs_human_review": True,
        "draft_payload": draft_payload,
        "primary_result": primary_result,
        "verification_result": verification_result,
        "escalation_result": escalation_result,
        "disagreements": disagreements,
        "source_text_length": len(payload.source_text),
        "created_at": now,
        "updated_at": now,
    }
    db.receipt_ai_drafts.insert_one(draft)
    record_domain_event("receipt_ai_drafts", "created")
    return _persisted_to_api(draft)

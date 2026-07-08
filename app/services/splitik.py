import hashlib
import json
import logging
import os
import time
import traceback

from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.rate_limit import (
    acquire_concurrency_limit,
    check_rate_limit,
    release_concurrency_limit,
)
from app.services import splitik_llm
from app.services.access import (
    active_event_memberships,
    assert_event_access,
    get_receipt_or_404,
    get_user_or_404,
)
from app.services.balances import get_event_balance_explanations, get_event_balances
from app.services.common import new_uuid, strip_mongo_id, utc_now, user_to_api_dict
from app.services.splitik_guardrails import (
    evaluate_planner_action,
    evaluate_assistant_message,
    evaluate_user_message,
    sanitize_message,
    strip_disallowed_emoji,
)
from app.services.splitik_interactions import log_interaction
from app.services import splitik_attachments, splitik_tools

logger = logging.getLogger("splitapp")
_MODES = {"general", "event", "receipt", "member"}
_SECONDS_PER_HOUR = 60 * 60
_SECONDS_PER_DAY = 24 * 60 * 60

_FORBIDDEN_CAPABILITIES = [
    "forbidden:impersonate_user",
    "forbidden:delete_event",
    "forbidden:edit_existing_money_state",
    "forbidden:mark_foreign_payment_paid",
]

_SYSTEM_PROMPT = """
Ты Сплитик, ассистент SplitApp. Отвечай на языке пользователя.
Используй только контекст и инструменты, которые передал backend.
Не утверждай, что изменил данные, если backend не вернул подтвержденный ресурс.
Для любых изменений объясняй шаг draft/подтверждения: сначала создается или
редактируется черновик, а реальные деньги меняются только после явного commit.
Не проси секреты, платежные данные, пароли, токены или приватные данные вне
контекста SplitApp. Не раскрывай личные траты другого пользователя вне общего
события и разрешенного backend-контекста.

Стиль ответа:
- Пиши спокойно и по делу, без маркетингового тона и самопрезентации.
- Строго без emoji, смайликов, эмотиконов и декоративных символов.
- Используй Markdown, который удобно читать в мобильном чате.
- Делай короткие абзацы по 1-2 предложения.
- Для вариантов действий используй маркированные списки через "- ".
- Выделяй важные статусы и суммы через **жирный текст**, но не делай весь ответ жирным.
- Если данных нет, скажи это прямо и предложи 1-2 следующих действия.
- Не начинай каждый ответ с приветствия, если пользователь уже находится в диалоге.
- Не используй английские технические слова вроде commit, если можно сказать "подтверждение".
- В конце не добавляй лишние вопросы, если уже дал понятный следующий шаг.
""".strip()


def _clean(document: dict) -> dict:
    return strip_mongo_id(document)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _limit_decision(reason: str, message: str) -> dict:
    return {"allowed": False, "reason": reason, "message": message}


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


def _available_tools(mode: str) -> list[str]:
    common_tools = [
        "splitik.get_active_draft",
        "splitik.get_recent_session_messages",
    ]
    mode_tools = {
        "general": ["splitik.get_user_spending_summary"],
        "event": ["splitik.get_event_history"],
        "receipt": ["splitik.get_event_history"],
        "member": ["splitik.get_event_history"],
    }
    return common_tools + mode_tools.get(mode, [])


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


def _event_draft_candidate(message: str, context: dict) -> dict | None:
    candidate = splitik_llm.generate_event_draft_candidate(
        user_message=message,
        context=context,
    )
    content = candidate.get("content", {})
    if not isinstance(content, dict) or content.get("intent") != "create_event":
        return None
    payload = content.get("payload")
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    if _looks_like_invalid_event_name(name):
        return None
    assistant_message = str(content.get("assistant_message") or "").strip()
    return {
        "name": name[:80],
        "assistant_message": assistant_message,
        "model_id": candidate.get("model_id"),
    }


def _looks_like_event_creation_request(message: str) -> bool:
    lowered = message.casefold()
    has_event = "событ" in lowered or "event" in lowered
    has_create_verb = any(
        marker in lowered
        for marker in (
            "создай",
            "создать",
            "создадим",
            "добавь",
            "добавить",
            "новое",
            "новый event",
            "create event",
        )
    )
    return has_event and has_create_verb


def _looks_like_invalid_event_name(name: str) -> bool:
    lowered = name.casefold()
    instruction_markers = (
        "не добавляй",
        "не добавлять",
        "не надо",
        "просто создай",
        "создай событие",
        "добавь событие",
    )
    if any(marker in lowered for marker in instruction_markers):
        return True
    if "чек" in lowered and not any(
        marker in lowered for marker in ("по чеку", "чекпоинт", "check")
    ):
        return True
    return False


def _receipt_clarifying_questions() -> list[dict]:
    return [
        {
            "id": "payer",
            "text": "Кто платил за этот чек?",
            "required": True,
        },
        {
            "id": "participants",
            "text": "Кто участвовал в этом чеке?",
            "required": True,
        },
        {
            "id": "split_details",
            "text": "Кто что ел или как делим сумму?",
            "required": True,
        },
    ]


def _answered_receipt_question_ids(message: str) -> list[str]:
    lowered = message.casefold()
    answered: list[str] = []
    if any(marker in lowered for marker in ("я плат", "платил я", "платила я", "оплатил")):
        answered.append("payer")
    if any(marker in lowered for marker in ("были все", "все участник", "участвовали все")):
        answered.append("participants")
    if any(marker in lowered for marker in ("делим поровну", "поровну", "равн")):
        answered.append("split_details")
    return answered


def _empty_draft_result() -> dict:
    return {
        "drafts": [],
        "assistant_message": None,
        "questions": [],
        "guardrail_decision": None,
        "intent": None,
        "model_ids": [],
    }


def _planner_context(
    db: Database,
    *,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    session_id: str,
) -> dict:
    event_id = _event_id_from_payload(payload)
    attachments = []
    attachment_ids = [str(attachment_id) for attachment_id in payload.attachment_ids]
    if attachment_ids:
        attachments = splitik_attachments.list_attachments_for_actor(
            db,
            actor_user_id=actor_user_id,
            attachment_ids=attachment_ids,
        )
    return {
        "mode": payload.mode.strip().lower(),
        "entry_point": _entry_point_summary(payload),
        "event_id": event_id,
        "attachment_ids": attachment_ids,
        "attachments": attachments,
        "recent_messages": splitik_tools.read_recent_session_messages(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            limit=6,
        ),
        "active_draft": splitik_tools.read_active_draft(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            event_id=event_id,
        ),
        "human_review_required": True,
        "allowed_actions": [
            "create_event_draft",
            "create_receipt_draft",
            "update_receipt_draft",
            "ask_clarifying_question",
        ],
    }


def _normalize_questions(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    questions: list[dict] = []
    for question in value:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or "").strip()
        text = str(question.get("text") or "").strip()
        if not question_id or not text:
            continue
        questions.append(
            {
                "id": question_id[:80],
                "text": text[:300],
                "required": bool(question.get("required", True)),
            }
        )
    return questions


def _execute_planner_actions(
    db: Database,
    *,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    session_id: str,
    candidate: dict,
) -> dict:
    content = candidate.get("content", {})
    if not isinstance(content, dict):
        return _empty_draft_result()
    actions = content.get("actions", [])
    if not isinstance(actions, list) or not actions:
        return _empty_draft_result()

    draft_actions = [
        action
        for action in actions
        if isinstance(action, dict)
        and action.get("type") in {"create_event_draft", "create_receipt_draft"}
    ]
    max_drafts_per_request = max(1, _env_int("SPLITIK_MAX_DRAFTS_PER_REQUEST", 3))
    if len(draft_actions) > max_drafts_per_request:
        decision = _limit_decision(
            "splitik_draft_request_limit",
            "Слишком много черновиков за один запрос. Разбейте задачу на несколько сообщений.",
        )
        return {
            **_empty_draft_result(),
            "assistant_message": decision["message"],
            "guardrail_decision": decision,
            "intent": "guardrail",
        }

    pending_limit = max(1, _env_int("SPLITIK_PENDING_DRAFT_LIMIT", 10))
    pending_count = db.splitik_drafts.count_documents(
        {"owner_user_id": actor_user_id, "status": "pending"}
    )
    if draft_actions and pending_count + len(draft_actions) > pending_limit:
        decision = _limit_decision(
            "splitik_pending_draft_limit",
            "У вас уже слишком много неподтвержденных черновиков. Подтвердите или удалите старые.",
        )
        return {
            **_empty_draft_result(),
            "assistant_message": decision["message"],
            "guardrail_decision": decision,
            "intent": "guardrail",
        }

    for action in actions:
        if not isinstance(action, dict):
            return {
                **_empty_draft_result(),
                "assistant_message": "Я не смог безопасно разобрать план действий.",
                "guardrail_decision": {
                    "allowed": False,
                    "reason": "invalid_planner_action",
                    "message": "Я не смог безопасно разобрать план действий.",
                },
                "intent": "guardrail",
            }
        decision = evaluate_planner_action(action)
        if not decision["allowed"]:
            return {
                **_empty_draft_result(),
                "assistant_message": decision["message"],
                "guardrail_decision": decision,
                "intent": "guardrail",
            }

    drafts: list[dict] = []
    questions: list[dict] = []
    model_id = candidate.get("model_id")
    model_metadata = {
        "model_id": model_id,
        "planner_intent": content.get("intent"),
    }

    for action in actions:
        action_type = action["type"]
        if action_type == "create_event_draft":
            payload_data = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            name = str(payload_data.get("name") or "").strip()
            if not name or _looks_like_invalid_event_name(name):
                continue
            drafts.append(
                splitik_tools.create_event_draft(
                    db,
                    actor_user_id=actor_user_id,
                    session_id=session_id,
                    payload={"name": name[:80]},
                    source="planner",
                    questions=_normalize_questions(action.get("questions")),
                    model_metadata=model_metadata,
                )
            )
        elif action_type == "create_receipt_draft":
            event_id = str(action.get("event_id") or _event_id_from_payload(payload) or "")
            payload_data = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            if not event_id or not payload_data:
                questions.extend(_normalize_questions(action.get("questions")))
                continue
            attachment_ids = [
                str(attachment_id) for attachment_id in action.get("attachment_ids", [])
            ]
            if attachment_ids:
                splitik_attachments.list_attachments_for_actor(
                    db,
                    actor_user_id=actor_user_id,
                    attachment_ids=attachment_ids,
                )
            drafts.append(
                splitik_tools.create_receipt_draft(
                    db,
                    actor_user_id=actor_user_id,
                    session_id=session_id,
                    event_id=event_id,
                    payload=payload_data,
                    source="planner",
                    attachment_ids=attachment_ids,
                    questions=_normalize_questions(action.get("questions")),
                    model_metadata=model_metadata,
                )
            )
        elif action_type == "update_receipt_draft":
            event_id = str(action.get("event_id") or _event_id_from_payload(payload) or "")
            draft_id = str(action.get("draft_id") or "")
            if not draft_id and event_id:
                latest = splitik_tools.latest_pending_draft(
                    db,
                    actor_user_id=actor_user_id,
                    session_id=session_id,
                    draft_type="create_receipt",
                    event_id=event_id,
                )
                draft_id = latest["id"] if latest else ""
            payload_patch = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            patch: dict = {"model_metadata": model_metadata}
            if payload_patch:
                patch["payload"] = payload_patch
            normalized_questions = _normalize_questions(action.get("questions"))
            if normalized_questions or "questions" in action:
                patch["questions"] = normalized_questions
            if draft_id:
                drafts.append(
                    splitik_tools.update_draft(
                        db,
                        actor_user_id=actor_user_id,
                        draft_id=draft_id,
                        patch=patch,
                    )
                )
        elif action_type == "ask_clarifying_question":
            questions.extend(_normalize_questions(action.get("questions")))

    assistant_message = str(content.get("assistant_message") or "").strip() or None
    intent = "draft" if drafts else "question" if questions else None
    return {
        "drafts": drafts,
        "assistant_message": assistant_message,
        "questions": questions,
        "guardrail_decision": None,
        "intent": intent,
        "model_ids": [str(model_id)] if model_id else [],
    }


def _planner_draft_result(
    db: Database,
    *,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    session_id: str,
) -> dict:
    try:
        candidate = splitik_llm.generate_splitik_plan_candidate(
            user_message=payload.message,
            context=_planner_context(
                db,
                payload=payload,
                actor_user_id=actor_user_id,
                session_id=session_id,
            ),
        )
    except HTTPException as exc:
        if exc.status_code == 503:
            return _empty_draft_result()
        raise
    return _execute_planner_actions(
        db,
        payload=payload,
        actor_user_id=actor_user_id,
        session_id=session_id,
        candidate=candidate,
    )


def _intent_router_context(payload: schemas.SplitikMessageRequest) -> dict:
    return {
        "mode": payload.mode.strip().lower(),
        "entry_point": _entry_point_summary(payload),
        "attachment_count": len(payload.attachment_ids),
        "human_review_required_for_mutations": True,
        "route_options": ["explain", "chat", "mutation"],
    }


def _heuristic_user_intent(payload: schemas.SplitikMessageRequest) -> str:
    lowered = payload.message.casefold()
    if payload.attachment_ids:
        return "mutation"
    mutation_markers = (
        "создай",
        "создать",
        "добавь",
        "добавить",
        "измени",
        "изменить",
        "поменяй",
        "поменять",
        "обнови",
        "обновить",
        "удали",
        "удалить",
        "распарси",
        "распарсить",
        "разбери чек",
        "разобрать чек",
        "добавить чек",
        "создать событие",
        "я платил",
        "я платила",
        "платил я",
        "платила я",
        "были все",
        "делим",
        "create",
        "add receipt",
    )
    if any(marker in lowered for marker in mutation_markers):
        return "mutation"
    explanation_markers = (
        "почему",
        "поясни",
        "объясни",
        "объяснить",
        "сколько",
        "кто кому",
        "кто мне должен",
        "кому я должен",
        "why",
        "explain",
    )
    if _is_expense_explanation_request(payload.message) or any(
        marker in lowered for marker in explanation_markers
    ):
        return "explain"
    return "chat"


def _classify_user_intent(payload: schemas.SplitikMessageRequest) -> tuple[str, str | None]:
    heuristic_intent = _heuristic_user_intent(payload)
    if heuristic_intent == "chat":
        return "chat", None

    try:
        candidate = splitik_llm.generate_splitik_intent_candidate(
            user_message=payload.message,
            context=_intent_router_context(payload),
        )
    except HTTPException as exc:
        if exc.status_code == 503:
            return heuristic_intent, None
        raise

    content = candidate.get("content", {})
    intent = str(content.get("intent") if isinstance(content, dict) else "").strip().lower()
    if intent not in {"explain", "chat", "mutation"}:
        intent = heuristic_intent
    model_id = candidate.get("model_id")
    return intent, str(model_id) if model_id else None


def _maybe_create_draft(
    db: Database,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    session_id: str,
) -> dict:
    mode = payload.mode.strip().lower()
    lowered = payload.message.casefold()
    user_intent, intent_model_id = _classify_user_intent(payload)
    if user_intent != "mutation":
        result = _empty_draft_result()
        if intent_model_id:
            result["model_ids"] = [intent_model_id]
        return result

    planner_result = _planner_draft_result(
        db,
        payload=payload,
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    if intent_model_id:
        planner_result["model_ids"] = [
            *planner_result.get("model_ids", []),
            intent_model_id,
        ]
    if (
        planner_result["drafts"]
        or planner_result["questions"]
        or planner_result["guardrail_decision"]
    ):
        return planner_result

    if mode == "general":
        if not _looks_like_event_creation_request(payload.message):
            return _empty_draft_result()
        recent_messages = splitik_tools.read_recent_session_messages(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            limit=6,
        )
        event_candidate = _event_draft_candidate(
            payload.message,
            context={
                "human_review_required": True,
                "recent_messages": recent_messages,
            },
        )
        if not event_candidate:
            return _empty_draft_result()
        draft = splitik_tools.create_event_draft(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            payload={"name": event_candidate["name"]},
            source="llm",
            model_metadata={
                "assistant_message": event_candidate["assistant_message"],
                "model_id": event_candidate["model_id"],
            },
        )
        return {
            **_empty_draft_result(),
            "drafts": [draft],
            "assistant_message": event_candidate["assistant_message"],
            "intent": "draft",
            "model_ids": [event_candidate["model_id"]] if event_candidate["model_id"] else [],
        }

    if mode != "event" or not payload.entry_point or not payload.entry_point.event_id:
        return _empty_draft_result()

    event_id = str(payload.entry_point.event_id)
    attachment_ids = [str(attachment_id) for attachment_id in payload.attachment_ids]
    if attachment_ids:
        attachments = splitik_attachments.list_attachments_for_actor(
            db,
            actor_user_id=actor_user_id,
            attachment_ids=attachment_ids,
        )
        candidate = splitik_llm.generate_receipt_image_candidate(
            model_role="primary",
            attachment_metadata=attachments[0],
            context={
                "event_id": event_id,
                "attachment_ids": attachment_ids,
                "human_review_required": True,
            },
        )
        content = candidate.get("content", {})
        receipt_payload = content.get("payload") if isinstance(content, dict) else None
        if not receipt_payload:
            return _empty_draft_result()
        questions = content.get("questions") if isinstance(content, dict) else None
        if not questions:
            questions = _receipt_clarifying_questions()
        draft = splitik_tools.create_receipt_draft(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            event_id=event_id,
            payload=receipt_payload,
            source="image",
            attachment_ids=attachment_ids,
            questions=questions,
        )
        return {**_empty_draft_result(), "drafts": [draft], "intent": "draft"}

    amount_kopecks = splitik_tools.amount_kopecks_from_text(payload.message)
    latest_receipt_draft = splitik_tools.latest_pending_draft(
        db,
        actor_user_id=actor_user_id,
        session_id=session_id,
        draft_type="create_receipt",
        event_id=event_id,
    )
    if latest_receipt_draft and latest_receipt_draft.get("questions"):
        answered_question_ids = _answered_receipt_question_ids(payload.message)
        if answered_question_ids:
            remaining_questions = [
                question
                for question in latest_receipt_draft.get("questions", [])
                if question.get("id") not in set(answered_question_ids)
            ]
            draft = splitik_tools.update_draft(
                db,
                actor_user_id=actor_user_id,
                draft_id=latest_receipt_draft["id"],
                patch={
                    "questions": remaining_questions,
                    "model_metadata": {"answered_question_ids": answered_question_ids},
                },
            )
            return {**_empty_draft_result(), "drafts": [draft], "intent": "draft"}
    if (
        latest_receipt_draft
        and amount_kopecks
        and any(marker in lowered for marker in ("поменяй", "измени", "исправь", "сумм"))
    ):
        payload_patch = dict(latest_receipt_draft["payload"])
        payload_patch["total_amount_kopecks"] = amount_kopecks
        if payload_patch.get("items"):
            payload_patch["items"][0]["cost_kopecks"] = amount_kopecks
        draft = splitik_tools.update_draft(
            db,
            actor_user_id=actor_user_id,
            draft_id=latest_receipt_draft["id"],
            patch={"payload": payload_patch},
        )
        return {**_empty_draft_result(), "drafts": [draft], "intent": "draft"}

    if not any(marker in lowered for marker in ("чек", "счет", "счёт", "заплатил")):
        return _empty_draft_result()

    receipt_payload = splitik_tools.build_simple_receipt_payload(
        db,
        event_id=event_id,
        actor_user_id=actor_user_id,
        message=payload.message,
    )
    if not receipt_payload:
        return _empty_draft_result()
    draft = splitik_tools.create_receipt_draft(
        db,
        actor_user_id=actor_user_id,
        session_id=session_id,
        event_id=event_id,
        payload=receipt_payload,
        questions=_receipt_clarifying_questions(),
    )
    return {**_empty_draft_result(), "drafts": [draft], "intent": "draft"}


def _is_expense_explanation_request(message: str) -> bool:
    lowered = message.casefold()
    return any(marker in lowered for marker in ("долж", "деньг", "трат", "потрат", "баланс"))


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


def _event_id_from_payload(payload: schemas.SplitikMessageRequest) -> str | None:
    if payload.entry_point and payload.entry_point.event_id:
        return str(payload.entry_point.event_id)
    return None


def _build_tool_results(
    db: Database,
    *,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    session_id: str,
) -> dict:
    mode = payload.mode.strip().lower()
    results = {
        "splitik.get_active_draft": splitik_tools.read_active_draft(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
        ),
        "splitik.get_recent_session_messages": splitik_tools.read_recent_session_messages(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            limit=6,
        ),
    }
    event_id = _event_id_from_payload(payload)
    if event_id and "splitik.get_event_history" in _available_tools(mode):
        results["splitik.get_event_history"] = splitik_tools.read_event_history(
            db,
            actor_user_id=actor_user_id,
            event_id=event_id,
            limit=10,
        )
    return results


def _build_conversation_state(
    *,
    session_id: str,
    mode: str,
    tool_results: dict,
) -> dict:
    state = {
        "session_id": session_id,
        "mode": mode,
        "recent_messages": tool_results.get("splitik.get_recent_session_messages", []),
    }
    active_draft = tool_results.get("splitik.get_active_draft")
    if active_draft:
        state["active_draft"] = active_draft
    return state


def _draft_questions(drafts: list[dict]) -> list[dict]:
    questions: list[dict] = []
    seen_ids: set[str] = set()
    for draft in drafts:
        for question in draft.get("questions", []):
            question_id = str(question.get("id") or "")
            if question_id in seen_ids:
                continue
            seen_ids.add(question_id)
            questions.append(question)
    return questions


def _draft_assistant_message(drafts: list[dict]) -> str | None:
    if not drafts:
        return None
    message = str(drafts[0].get("model_metadata", {}).get("assistant_message") or "").strip()
    return message or None


def _draft_suggested_actions(drafts: list[dict]) -> list[dict]:
    return [
        {
            "type": "commit_draft",
            "label": "Подтвердить",
            "draft_id": draft["id"],
        }
        for draft in drafts
        if draft.get("status") == "pending"
    ]


def _entry_point_summary(payload: schemas.SplitikMessageRequest) -> dict:
    entry_point = payload.entry_point
    if entry_point is None:
        return {"entry_point_type": None}
    return {
        "entry_point_type": entry_point.type,
        "event_id": str(entry_point.event_id) if entry_point.event_id else None,
        "receipt_id": str(entry_point.receipt_id) if entry_point.receipt_id else None,
        "target_user_id": str(entry_point.target_user_id) if entry_point.target_user_id else None,
    }


def _count_context_values(context: dict) -> dict:
    counts: dict[str, int] = {}
    for key, value in context.items():
        if isinstance(value, list):
            counts[key] = len(value)
        elif isinstance(value, dict):
            counts[key] = len(value)
    return counts


def _context_summary(
    payload: schemas.SplitikMessageRequest,
    *,
    mode: str,
    context: dict | None = None,
    tools: list[str] | None = None,
    drafts: list[dict] | None = None,
) -> dict:
    summary = {
        "mode": mode,
        "message_length": len(payload.message),
        "attachment_count": len(payload.attachment_ids),
        "available_tools": tools or [],
        "draft_count": len(drafts or []),
        "context_counts": _count_context_values(context or {}),
    }
    summary.update(_entry_point_summary(payload))
    return summary


def _error_payload(exc: Exception) -> dict:
    status_code = exc.status_code if isinstance(exc, HTTPException) else None
    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {
        "type": type(exc).__name__,
        "http_status": status_code,
        "message": sanitize_message(str(detail)),
        "traceback_hash": hashlib.sha256(stack.encode("utf-8")).hexdigest(),
    }


def _log_splitik_failure(
    db: Database,
    *,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    request_id: str | None,
    session_id: str | None,
    message_id: str,
    mode: str,
    stage: str,
    started: float,
    context: dict | None,
    tools: list[str] | None,
    drafts: list[dict] | None,
    guardrail_decision: dict | None,
    exc: Exception,
) -> None:
    error = _error_payload(exc)
    logger.error(
        json.dumps(
            {
                "level": "ERROR",
                "message": "splitik_message_failed",
                "request_id": request_id,
                "actor_user_id": actor_user_id,
                "session_id": session_id,
                "message_id": message_id,
                "stage": stage,
                "error": error,
            },
            default=str,
        ),
        exc_info=True,
    )
    try:
        log_interaction(
            db,
            actor_user_id=actor_user_id,
            session_id=session_id,
            message_id=message_id,
            sanitized_user_message=payload.message,
            intent="error",
            context_scope=mode,
            assistant_message="",
            guardrail_decision=guardrail_decision or {},
            request_id=request_id,
            status="error",
            stage=stage,
            model_ids=["primary"] if stage.startswith("llm.") else [],
            context_summary=_context_summary(
                payload,
                mode=mode,
                context=context,
                tools=tools,
                drafts=drafts,
            ),
            tool_calls=[{"name": name, "status": "available"} for name in (tools or [])],
            draft_ids=[str(draft["id"]) for draft in (drafts or [])],
            latency_ms=round((time.monotonic() - started) * 1000, 2),
            error=error,
        )
    except Exception:
        logger.error("splitik_failure_log_write_failed", exc_info=True)


def send_splitik_message(
    db: Database,
    payload: schemas.SplitikMessageRequest,
    actor_user_id: str,
    request_id: str | None = None,
) -> dict:
    started = time.monotonic()
    mode = payload.mode.strip().lower()
    session: dict | None = None
    message_id = new_uuid()
    stage = "actor.lookup"
    guardrail_decision: dict | None = None
    context: dict = {}
    drafts: list[dict] = []
    tools: list[str] = []
    concurrency_acquired = False
    try:
        get_user_or_404(db, actor_user_id)
        stage = "rate_limit"
        if len(payload.attachment_ids) > max(1, _env_int("SPLITIK_ATTACHMENTS_PER_MESSAGE", 3)):
            raise HTTPException(
                status_code=429,
                detail="Too many Splitik attachments in one message.",
            )
        check_rate_limit(
            "splitik.messages.hour",
            actor_user_id,
            max_requests=_env_int("SPLITIK_MESSAGE_HOURLY_LIMIT", 10),
            window_seconds=_SECONDS_PER_HOUR,
            detail="Splitik hourly message limit exceeded.",
        )
        check_rate_limit(
            "splitik.messages.day",
            actor_user_id,
            max_requests=_env_int("SPLITIK_MESSAGE_DAILY_LIMIT", 30),
            window_seconds=_SECONDS_PER_DAY,
            detail="Splitik daily message limit exceeded.",
        )
        acquire_concurrency_limit(
            "splitik.messages.concurrent",
            actor_user_id,
            max_concurrent=_env_int("SPLITIK_MESSAGE_CONCURRENT_LIMIT", 1),
            detail="Another Splitik request is already running.",
        )
        concurrency_acquired = True
        stage = "guardrail.user"
        guardrail_decision = evaluate_user_message(payload.message, context_scope=mode)
        if not guardrail_decision["allowed"]:
            stage = "session.load"
            session = _get_or_create_session(db, payload, actor_user_id)
            now = utc_now()
            reply = guardrail_decision["message"]
            stage = "session.write"
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
                request_id=request_id,
                status="success",
                stage="completed",
                context_summary=_context_summary(payload, mode=mode),
                latency_ms=round((time.monotonic() - started) * 1000, 2),
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

        stage = "session.load"
        session = _get_or_create_session(db, payload, actor_user_id)
        stage = "context.build"
        context, chips, capabilities = _build_context(db, payload, actor_user_id)
        stage = "drafts.create"
        draft_result = _maybe_create_draft(db, payload, actor_user_id, session["id"])
        drafts = draft_result["drafts"]
        questions = _draft_questions(drafts) + draft_result["questions"]
        if draft_result["guardrail_decision"]:
            guardrail_decision = draft_result["guardrail_decision"]
        if drafts:
            context["drafts"] = drafts
        tools = _available_tools(mode)
        stage = "tools.build"
        tool_results = _build_tool_results(
            db,
            payload=payload,
            actor_user_id=actor_user_id,
            session_id=session["id"],
        )
        context["available_tools"] = tools
        context["tool_results"] = tool_results
        context["conversation_state"] = _build_conversation_state(
            session_id=session["id"],
            mode=mode,
            tool_results=tool_results,
        )
        draft_reply = draft_result["assistant_message"] or _draft_assistant_message(drafts)
        if draft_reply or draft_result["intent"] in {"question", "guardrail"}:
            reply = draft_reply or (
                questions[0]["text"] if questions else "Я не смог безопасно разобрать запрос."
            )
            stage = "guardrail.assistant"
            if not guardrail_decision or guardrail_decision["allowed"]:
                post_guardrail_decision = evaluate_assistant_message(
                    reply,
                    committed_resource=False,
                )
                if not post_guardrail_decision["allowed"]:
                    reply = post_guardrail_decision["message"]
                    guardrail_decision = post_guardrail_decision
            now = utc_now()
            intent = draft_result["intent"] or "draft"
            if not guardrail_decision["allowed"]:
                intent = "guardrail"
            stage = "session.write"
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
                intent=intent,
                context_scope=mode,
                assistant_message=reply,
                guardrail_decision=guardrail_decision,
                request_id=request_id,
                status="success",
                stage="completed",
                model_ids=draft_result["model_ids"]
                or [
                    str(model_id)
                    for model_id in {
                        draft.get("model_metadata", {}).get("model_id") for draft in drafts
                    }
                    if model_id
                ],
                context_summary=_context_summary(
                    payload,
                    mode=mode,
                    context=context,
                    tools=tools,
                    drafts=drafts,
                ),
                tool_calls=[
                    {"name": name, "status": "completed"} for name in context["tool_results"].keys()
                ],
                draft_ids=[str(draft["id"]) for draft in drafts],
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return {
                "session_id": session["id"],
                "message_id": message_id,
                "assistant_message": reply,
                "mode": mode,
                "intent": intent,
                "guardrail_decision": guardrail_decision,
                "context_chips": chips,
                "capabilities": capabilities,
                "drafts": drafts,
                "questions": questions,
                "suggested_actions": _draft_suggested_actions(drafts),
            }
        explanation_requested = _is_expense_explanation_request(payload.message)
        if explanation_requested:
            context["user_balance_summary"] = splitik_tools.read_user_balance_summary(
                db, actor_user_id=actor_user_id
            )
            context["tool_results"]["splitik.get_user_spending_summary"] = context[
                "user_balance_summary"
            ]

        stage = "llm.generate_reply"
        reply_model_role = "primary" if explanation_requested else "fast_chat"
        reply = splitik_llm.generate_splitik_reply(
            system_prompt=_SYSTEM_PROMPT,
            user_message=payload.message,
            context=context,
            model_role=reply_model_role,
        )
        reply = strip_disallowed_emoji(reply)
        stage = "guardrail.assistant"
        post_guardrail_decision = evaluate_assistant_message(
            reply,
            committed_resource=False,
        )
        if not post_guardrail_decision["allowed"]:
            reply = post_guardrail_decision["message"]
            guardrail_decision = post_guardrail_decision
        now = utc_now()
        intent = "draft" if drafts else "explain" if explanation_requested else "chat"
        if not guardrail_decision["allowed"]:
            intent = "guardrail"
        stage = "session.write"
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
            intent=intent,
            context_scope=mode,
            assistant_message=reply,
            guardrail_decision=guardrail_decision,
            request_id=request_id,
            status="success",
            stage="completed",
            model_ids=[reply_model_role],
            context_summary=_context_summary(
                payload,
                mode=mode,
                context=context,
                tools=tools,
                drafts=drafts,
            ),
            tool_calls=[
                {"name": name, "status": "completed"} for name in context["tool_results"].keys()
            ],
            draft_ids=[str(draft["id"]) for draft in drafts],
            latency_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return {
            "session_id": session["id"],
            "message_id": message_id,
            "assistant_message": reply,
            "mode": mode,
            "intent": intent,
            "guardrail_decision": guardrail_decision,
            "context_chips": chips,
            "capabilities": capabilities,
            "drafts": drafts,
            "questions": questions,
            "suggested_actions": [],
        }
    except Exception as exc:
        _log_splitik_failure(
            db,
            payload=payload,
            actor_user_id=actor_user_id,
            request_id=request_id,
            session_id=session["id"] if session else None,
            message_id=message_id,
            mode=mode,
            stage=stage,
            started=started,
            context=context,
            tools=tools,
            drafts=drafts,
            guardrail_decision=guardrail_decision,
            exc=exc,
        )
        raise
    finally:
        if concurrency_acquired:
            release_concurrency_limit("splitik.messages.concurrent", actor_user_id)


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

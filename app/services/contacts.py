import hashlib
import re

from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.services.access import get_user_or_404
from app.services.common import new_uuid, strip_mongo_id, user_to_api_dict, utc_now


_PHONE_DIGITS_RE = re.compile(r"\D+")


def normalize_phone_number(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("phone number is empty")

    has_plus = raw.startswith("+")
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if not digits:
        raise ValueError("phone number has no digits")

    if has_plus:
        normalized = f"+{digits}"
    elif len(digits) == 11 and digits.startswith("8"):
        normalized = f"+7{digits[1:]}"
    elif len(digits) == 11 and digits.startswith("7"):
        normalized = f"+{digits}"
    elif len(digits) == 10:
        normalized = f"+7{digits}"
    else:
        normalized = f"+{digits}"

    if len(normalized) < 8 or len(normalized) > 16:
        raise ValueError("phone number must contain 7-15 digits")
    return normalized


def phone_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_display_name(value: str) -> str:
    display_name = " ".join(value.strip().split())
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name cannot be empty.")
    return display_name


def _matched_user_to_api(user: dict | None, contact_display_name: str) -> dict | None:
    if not user:
        return None
    data = user_to_api_dict(user)
    data["display_name"] = contact_display_name
    return data


def _contact_to_api(db: Database, contact: dict) -> dict:
    matched_user = None
    matched_user_id = contact.get("matched_user_id")
    if matched_user_id:
        matched_user = db.users.find_one({"id": matched_user_id})
    data = strip_mongo_id(contact)
    data["matched_user"] = _matched_user_to_api(matched_user, data["display_name"])
    return data


def _first_valid_phone(phone_numbers: list[str]) -> str | None:
    for phone in phone_numbers:
        try:
            return normalize_phone_number(phone)
        except ValueError:
            continue
    return None


@track_service_operation("contacts.import")
def import_user_contacts(
    db: Database, actor_user_id: str, payload: schemas.ContactImportRequest
) -> dict:
    get_user_or_404(db, actor_user_id)
    now = utc_now()
    imported = 0
    skipped = 0
    items: list[dict] = []

    for item in payload.contacts:
        phone_number = _first_valid_phone(item.phone_numbers)
        if phone_number is None:
            skipped += 1
            continue

        display_name = _clean_display_name(item.display_name)
        hashed = phone_hash(phone_number)
        matched_user = db.users.find_one({"phone_number": phone_number})
        existing = db.user_contacts.find_one({"owner_user_id": actor_user_id, "phone_hash": hashed})
        contact_id = existing["id"] if existing else new_uuid()
        created_at = existing.get("created_at", now) if existing else now
        contact = {
            "id": contact_id,
            "owner_user_id": actor_user_id,
            "display_name": display_name,
            "phone_number": phone_number,
            "phone_hash": hashed,
            "matched_user_id": matched_user["id"] if matched_user else None,
            "created_at": created_at,
            "updated_at": now,
        }
        db.user_contacts.update_one(
            {"owner_user_id": actor_user_id, "phone_hash": hashed},
            {"$set": contact},
            upsert=True,
        )
        imported += 1
        items.append(_contact_to_api(db, contact))

    record_domain_event("contacts", "imported")
    return {
        "imported": imported,
        "matched": sum(1 for item in items if item.get("matched_user_id")),
        "skipped": skipped,
        "items": items,
    }


@track_service_operation("contacts.list")
def list_user_contacts(db: Database, actor_user_id: str, *, limit: int, offset: int) -> dict:
    get_user_or_404(db, actor_user_id)
    query = {"owner_user_id": actor_user_id}
    total = db.user_contacts.count_documents(query)
    cursor = db.user_contacts.find(query).sort("display_name", 1).skip(offset).limit(limit)
    return {
        "items": [_contact_to_api(db, contact) for contact in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }

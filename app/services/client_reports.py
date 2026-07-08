from datetime import UTC, datetime
from uuid import uuid4

from pymongo.database import Database

from app import schemas
from app.services.common import strip_mongo_id

ALLOWED_METADATA_KEYS = frozenset(
    {
        "api_status",
        "api_path",
        "component",
        "screen_label",
        "action",
        "error_name",
        "error_message",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _sanitize_metadata(metadata: dict) -> dict:
    sanitized: dict = {}
    for key, value in metadata.items():
        if key not in ALLOWED_METADATA_KEYS:
            continue
        if isinstance(value, str):
            sanitized[key] = value[:240]
        elif isinstance(value, bool) or isinstance(value, int) or value is None:
            sanitized[key] = value
    return sanitized


def create_client_report(
    db: Database,
    payload: schemas.ClientReportCreate,
    *,
    actor_user_id: str | None,
    client_ip: str | None,
) -> dict:
    report = {
        "id": str(uuid4()),
        "kind": payload.kind,
        "severity": payload.severity,
        "screen": payload.screen,
        "message": payload.message.strip(),
        "user_description": (
            payload.user_description.strip() if payload.user_description else None
        ),
        "request_id": payload.request_id,
        "client_trace_id": payload.client_trace_id,
        "app_version": payload.app_version,
        "url_path": payload.url_path,
        "user_agent": payload.user_agent,
        "online": payload.online,
        "contact_allowed": payload.contact_allowed,
        "contact": payload.contact.strip() if payload.contact_allowed and payload.contact else None,
        "metadata": _sanitize_metadata(payload.metadata),
        "actor_user_id": actor_user_id,
        "client_ip": client_ip,
        "source": "pwa",
        "status": "new",
        "created_at": utc_now(),
    }
    db.client_feedback_reports.insert_one(report)
    return strip_mongo_id(report)

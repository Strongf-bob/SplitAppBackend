import os
import time
from pathlib import Path

import httpx
import jwt
from fastapi import HTTPException
from pymongo.database import Database

from app import schemas
from app.core.monitoring import record_domain_event, track_service_operation
from app.services.access import get_user_or_404
from app.services.common import active_filter, new_uuid, record_audit_event, strip_mongo_id, utc_now


_SUPPORTED_PLATFORMS = {"ios"}
_SUPPORTED_PROVIDERS = {"apns"}
_SUPPORTED_ENVIRONMENTS = {"sandbox", "production"}


class NotificationProviderNotConfigured(RuntimeError):
    pass


def _device_to_api_dict(device: dict) -> dict:
    cleaned = strip_mongo_id(device)
    cleaned.pop("token", None)
    cleaned.pop("deleted_at", None)
    return cleaned


def _apns_private_key() -> str:
    raw_key = os.getenv("APNS_PRIVATE_KEY", "").strip()
    if raw_key:
        return raw_key.replace("\\n", "\n")

    key_path = os.getenv("APNS_PRIVATE_KEY_PATH", "").strip()
    if key_path:
        return Path(key_path).read_text(encoding="utf-8")

    raise NotificationProviderNotConfigured("APNS private key is not configured.")


def _apns_config() -> dict[str, str]:
    config = {
        "team_id": os.getenv("APNS_TEAM_ID", "").strip(),
        "key_id": os.getenv("APNS_KEY_ID", "").strip(),
        "bundle_id": os.getenv("APNS_BUNDLE_ID", "").strip(),
        "private_key": _apns_private_key(),
    }
    if not all(config.values()):
        raise NotificationProviderNotConfigured("APNS credentials are not fully configured.")
    return config


def _apns_host(environment: str) -> str:
    if environment == "production":
        return "https://api.push.apple.com"
    return "https://api.sandbox.push.apple.com"


def _apns_provider_token(config: dict[str, str]) -> str:
    return jwt.encode(
        {"iss": config["team_id"], "iat": int(time.time())},
        config["private_key"],
        algorithm="ES256",
        headers={"alg": "ES256", "kid": config["key_id"]},
    )


def _send_apns_notification(
    device: dict,
    *,
    title: str,
    body: str,
    data: dict[str, str],
) -> None:
    config = _apns_config()
    custom_data = {key: value for key, value in data.items() if key != "aps"}
    payload = {
        "aps": {
            "alert": {
                "title": title,
                "body": body,
            },
            "sound": "default",
        },
        **custom_data,
    }
    headers = {
        "authorization": f"bearer {_apns_provider_token(config)}",
        "apns-topic": config["bundle_id"],
        "apns-push-type": "alert",
        "apns-priority": "10",
    }
    url = f"{_apns_host(device['environment'])}/3/device/{device['token']}"

    with httpx.Client(http2=True, timeout=10.0) as client:
        response = client.post(url, json=payload, headers=headers)
    if response.status_code == 410:
        raise HTTPException(status_code=410, detail="Device token is no longer registered.")
    if response.status_code >= 400:
        detail = response.text.strip() or f"APNS returned {response.status_code}."
        raise RuntimeError(detail)


@track_service_operation("notifications.register_device")
def register_notification_device(
    db: Database,
    actor_user_id: str,
    payload: schemas.NotificationDeviceRegister,
) -> dict:
    get_user_or_404(db, actor_user_id)
    platform = payload.platform.strip().lower()
    provider = payload.provider.strip().lower()
    environment = payload.environment.strip().lower()
    token = payload.token.strip()

    if platform not in _SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail="Unsupported notification platform.")
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported notification provider.")
    if environment not in _SUPPORTED_ENVIRONMENTS:
        raise HTTPException(status_code=400, detail="Unsupported notification environment.")
    if not token:
        raise HTTPException(status_code=400, detail="Device token cannot be empty.")

    now = utc_now()
    existing = db.notification_devices.find_one(
        {"provider": provider, "environment": environment, "token": token}
    )
    if existing:
        device_id = existing["id"]
        created_at = existing.get("created_at", now)
    else:
        device_id = new_uuid()
        created_at = now

    document = {
        "id": device_id,
        "user_id": actor_user_id,
        "platform": platform,
        "provider": provider,
        "token": token,
        "environment": environment,
        "enabled": True,
        "created_at": created_at,
        "updated_at": now,
        "last_seen_at": now,
    }
    db.notification_devices.update_one(
        {"provider": provider, "environment": environment, "token": token},
        {"$set": document, "$unset": {"deleted_at": ""}},
        upsert=True,
    )
    record_domain_event("notifications", "device_registered")
    record_audit_event(
        db,
        action="notification_device.registered",
        resource_type="notification_device",
        resource_id=device_id,
        actor_user_id=actor_user_id,
    )
    return _device_to_api_dict(db.notification_devices.find_one({"id": device_id}))


@track_service_operation("notifications.list_devices")
def list_notification_devices(
    db: Database,
    actor_user_id: str,
    *,
    limit: int,
    offset: int,
) -> dict:
    get_user_or_404(db, actor_user_id)
    query = active_filter({"user_id": actor_user_id})
    total = db.notification_devices.count_documents(query)
    cursor = db.notification_devices.find(query).sort("last_seen_at", -1).skip(offset).limit(limit)
    return {
        "items": [_device_to_api_dict(device) for device in cursor],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@track_service_operation("notifications.delete_device")
def delete_notification_device(db: Database, actor_user_id: str, device_id: str) -> None:
    get_user_or_404(db, actor_user_id)
    device = db.notification_devices.find_one(
        active_filter({"id": device_id, "user_id": actor_user_id})
    )
    if not device:
        raise HTTPException(status_code=404, detail="Notification device not found.")

    db.notification_devices.update_one(
        {"id": device_id, "user_id": actor_user_id},
        {"$set": {"enabled": False, "deleted_at": utc_now(), "updated_at": utc_now()}},
    )
    record_domain_event("notifications", "device_deleted")
    record_audit_event(
        db,
        action="notification_device.deleted",
        resource_type="notification_device",
        resource_id=device_id,
        actor_user_id=actor_user_id,
    )


@track_service_operation("notifications.send_user")
def send_user_notification(
    db: Database,
    user_id: str,
    *,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict:
    get_user_or_404(db, user_id)
    payload_data = data or {}
    devices = list(
        db.notification_devices.find(active_filter({"user_id": user_id, "enabled": True})).sort(
            "last_seen_at", -1
        )
    )
    results: list[dict] = []

    for device in devices:
        status = "sent"
        error = None
        try:
            if device["provider"] != "apns":
                raise RuntimeError("Unsupported notification provider.")
            _send_apns_notification(device, title=title, body=body, data=payload_data)
        except NotificationProviderNotConfigured as exc:
            status = "failed"
            error = str(exc)
        except HTTPException as exc:
            status = "failed"
            error = str(exc.detail)
            if exc.status_code == 410:
                db.notification_devices.update_one(
                    {"id": device["id"]},
                    {"$set": {"enabled": False, "deleted_at": utc_now(), "updated_at": utc_now()}},
                )
        except Exception as exc:
            status = "failed"
            error = str(exc)

        results.append(
            {
                "device_id": device["id"],
                "provider": device["provider"],
                "status": status,
                "error": error,
            }
        )

    sent = sum(1 for result in results if result["status"] == "sent")
    failed = len(results) - sent
    record_domain_event("notifications", "send_attempted")
    return {
        "attempted": len(results),
        "sent": sent,
        "failed": failed,
        "results": results,
    }

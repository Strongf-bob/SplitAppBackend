from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Notifications"])


@router.post("/api/notification-devices", response_model=schemas.NotificationDevice)
def register_notification_device(
    payload: schemas.NotificationDeviceRegister,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.register_notification_device(db, current_user_id, payload)


@router.get("/api/notification-devices", response_model=schemas.NotificationDevicePage)
def list_notification_devices(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_notification_devices(db, current_user_id, limit=limit, offset=offset)


@router.delete("/api/notification-devices/{id}", status_code=204)
def delete_notification_device(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.delete_notification_device(db, current_user_id, str(id))
    return Response(status_code=204)


@router.post("/api/notifications/test", response_model=schemas.NotificationSendResponse)
def send_test_notification(
    payload: schemas.NotificationTestRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.send_user_notification(
        db,
        current_user_id,
        title=payload.title,
        body=payload.body,
        data=payload.data,
    )

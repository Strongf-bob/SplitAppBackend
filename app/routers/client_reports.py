import jwt
from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pymongo.database import Database

from app import schemas, services
from app.core import tokens
from app.core.rate_limit import check_rate_limit
from app.dependencies import bearer_scheme, get_db

router = APIRouter(tags=["Client Reports"])


def _optional_actor_user_id(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if not credentials or credentials.scheme.lower() != "bearer":
        return None
    try:
        return tokens.decode_access_token(credentials.credentials)
    except (RuntimeError, jwt.InvalidTokenError):
        return None


@router.post(
    "/api/client-reports",
    response_model=schemas.ClientReportCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_client_report(
    payload: schemas.ClientReportCreate,
    request: Request,
    db: Database = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    actor_user_id = _optional_actor_user_id(credentials)
    client_ip = request.client.host if request.client else None
    check_rate_limit("client_reports", actor_user_id or client_ip or "unknown")
    report = services.create_client_report(
        db,
        payload,
        actor_user_id=actor_user_id,
        client_ip=client_ip,
    )
    return {
        "id": report["id"],
        "status": report["status"],
        "friendly_message": "Спасибо. Мы получили сообщение и посмотрим его.",
    }

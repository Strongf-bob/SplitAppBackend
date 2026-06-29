from fastapi import APIRouter, HTTPException, Request, Response

from app.core.db import ping_mongodb
from app.core.monitoring import metrics_response

router = APIRouter(tags=["Health"])


@router.get("/api/ping")
def ping() -> dict[str, str]:
    return {"message": "pong"}


@router.get("/api/health/db")
def db_health(request: Request) -> dict[str, str]:
    try:
        ping_mongodb(request.app)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="MongoDB ping failed") from exc
    return {"message": "MongoDB connected"}


@router.get("/api/metrics")
def metrics() -> Response:
    body, media_type = metrics_response()
    return Response(content=body, media_type=media_type)

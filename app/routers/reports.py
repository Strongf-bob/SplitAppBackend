from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pymongo.database import Database

from app import services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Reports"])


@router.get("/api/receipt-categories", response_model=list[str])
def list_receipt_categories() -> list[str]:
    return services.list_receipt_categories()


@router.get("/api/events/{id}/export.csv")
def export_event_csv(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    csv_body = services.build_event_csv_export(db, str(id), current_user_id)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="event-{id}-export.csv"'},
    )

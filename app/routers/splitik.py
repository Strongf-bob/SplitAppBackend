from uuid import UUID

from fastapi import APIRouter, Depends
from pymongo.database import Database

from app import schemas
from app.dependencies import get_actor_user_id, get_db
from app.services import splitik

router = APIRouter(tags=["Splitik"])


@router.post("/api/splitik/messages", response_model=schemas.SplitikMessageResponse)
def send_message(
    payload: schemas.SplitikMessageRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.send_splitik_message(db, payload, current_user_id)


@router.get("/api/splitik/sessions/{id}", response_model=schemas.SplitikSession)
def get_session(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.get_splitik_session(db, str(id), current_user_id)


@router.post("/api/splitik/drafts/{id}/commit", response_model=schemas.SplitikDraftCommitResponse)
def commit_draft(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.commit_splitik_draft(db, str(id), current_user_id)

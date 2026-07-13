from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile, status
from pymongo.database import Database

from app import schemas
from app.dependencies import get_actor_user_id, get_db, get_s3
from app.services import splitik, splitik_attachments
from app.services.idempotency import run_idempotent_create

router = APIRouter(tags=["Splitik"])


@router.post(
    "/api/splitik/attachments",
    response_model=schemas.SplitikAttachment,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    file: UploadFile = File(...),
    db: Database = Depends(get_db),
    s3=Depends(get_s3),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik_attachments.create_attachment(
        db,
        s3,
        actor_user_id=current_user_id,
        filename=file.filename or "attachment",
        content_type=file.content_type or "application/octet-stream",
        content=await file.read(),
    )


@router.post("/api/splitik/messages", response_model=schemas.SplitikMessageResponse)
def send_message(
    payload: schemas.SplitikMessageRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    request_id = getattr(request.state, "request_id", None)
    return run_idempotent_create(
        db,
        actor_user_id=current_user_id,
        scope="splitik.message",
        key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        create=lambda: splitik.send_splitik_message(
            db,
            payload,
            current_user_id,
            request_id=request_id,
            s3_provider=lambda: get_s3(request),
        ),
    )


@router.get("/api/splitik/sessions/{id}", response_model=schemas.SplitikSession)
def get_session(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.get_splitik_session(db, str(id), current_user_id)


@router.get("/api/splitik/drafts/{id}", response_model=schemas.SplitikDraft)
def get_draft(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.get_splitik_draft(db, str(id), current_user_id)


@router.patch("/api/splitik/drafts/{id}", response_model=schemas.SplitikDraft)
def update_draft(
    id: UUID,
    payload: schemas.SplitikDraftUpdateRequest,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.update_splitik_draft(db, str(id), payload, current_user_id)


@router.post("/api/splitik/drafts/{id}/commit", response_model=schemas.SplitikDraftCommitResponse)
def commit_draft(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
):
    return splitik.commit_splitik_draft(db, str(id), current_user_id)

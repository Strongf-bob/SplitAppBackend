from typing import Any

from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.dependencies import get_db, get_s3
from app.services.user_avatar import get_avatar_redirect

router = APIRouter(tags=["Avatars"])


@router.get("/avatars/{user_id}", include_in_schema=False)
def get_avatar(
    user_id: str,
    db: Database = Depends(get_db),
    s3: Any = Depends(get_s3),
):
    """Serve public profile avatars for image clients that cannot attach bearer tokens."""
    return get_avatar_redirect(db, s3, user_id)

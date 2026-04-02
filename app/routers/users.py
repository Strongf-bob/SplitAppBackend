from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_db

router = APIRouter(tags=["Users"])


@router.post("/api/users", response_model=schemas.User, status_code=status.HTTP_201_CREATED)
def create_user(payload: schemas.UserCreate, db: Database = Depends(get_db)) -> dict:
    return services.create_user(db, payload)


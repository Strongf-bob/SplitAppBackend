from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from pymongo.database import Database

from app import schemas, services
from app.dependencies import get_actor_user_id, get_db

router = APIRouter(tags=["Friends"])


@router.post("/api/friends", response_model=schemas.Friendship, status_code=status.HTTP_201_CREATED)
def create_friend_request(
    payload: schemas.FriendRequestCreate,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_friend_request(db, payload, current_user_id)


@router.post(
    "/api/friend-invites", response_model=schemas.FriendInvite, status_code=status.HTTP_201_CREATED
)
def create_friend_invite(
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.create_friend_invite(db, current_user_id)


@router.get("/api/friend-invites/{token}/preview", response_model=schemas.FriendInvitePreview)
def preview_friend_invite(
    token: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.preview_friend_invite(db, token, current_user_id)


@router.post("/api/friend-invites/{token}/accept", response_model=schemas.Friendship)
def accept_friend_invite(
    token: str,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.accept_friend_invite(db, token, current_user_id)


@router.delete("/api/friend-invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_friend_invite(
    invite_id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.revoke_friend_invite(db, str(invite_id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/friends", response_model=schemas.FriendshipPage)
def list_friendships(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.list_friendships(
        db, current_user_id, status_filter=status_filter, limit=limit, offset=offset
    )


@router.post("/api/friends/{id}/accept", response_model=schemas.Friendship)
def accept_friend_request(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.accept_friend_request(db, str(id), current_user_id)


@router.post("/api/friends/{id}/reject", response_model=schemas.Friendship)
def reject_friend_request(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.reject_friend_request(db, str(id), current_user_id)


@router.delete("/api/friends/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friendship(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> Response:
    services.remove_friendship(db, str(id), current_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/friends/{id}/block", response_model=schemas.Friendship)
def block_friendship(
    id: UUID,
    db: Database = Depends(get_db),
    current_user_id: str = Depends(get_actor_user_id),
) -> dict:
    return services.block_friendship(db, str(id), current_user_id)

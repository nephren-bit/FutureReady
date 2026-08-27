"""
routers/admin.py

The Admin API (Nhóm B, Task 13 / Plans.md B6): list accounts, lock/unlock
via `is_active`. There is no delete -- locking is the removal mechanism,
matching `UserORM`'s own doc ("rows are never deleted, so a locked user's
practice-session history stays intact").

Locking takes effect on the very next request, not at the token's 7-day
expiry: `require_admin`/`get_current_user` (routers/deps.py) already
re-read `is_active` from the DB on every call, so nothing extra is needed
here for that -- this router only ever changes the flag, it never has to
enforce it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from db.models import UserORM
from db.session import get_db
from models.auth_models import AdminSetUserActiveRequest, AdminUserResponse
from models.responses import ErrorResponse
from routers.deps import require_admin
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_ERROR_RESPONSES = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}


@router.get(
    "/users",
    response_model=list[AdminUserResponse],
    responses=_ERROR_RESPONSES,
    summary="List every account, most recently created first.",
)
async def list_users(
    current_user: UserORM = Depends(require_admin), db: DBSession = Depends(get_db)
) -> list[AdminUserResponse]:
    users = db.query(UserORM).order_by(UserORM.created_at.desc()).all()
    return [AdminUserResponse.from_orm_user(user) for user in users]


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    responses=_ERROR_RESPONSES,
    summary="Lock or unlock an account via is_active. Never deletes it.",
)
async def set_user_active(
    user_id: uuid.UUID,
    body: AdminSetUserActiveRequest,
    current_user: UserORM = Depends(require_admin),
    db: DBSession = Depends(get_db),
) -> AdminUserResponse:
    user = db.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản.")

    user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    logger.info("Account %s set is_active=%s by admin %s", user.id, user.is_active, current_user.id)
    return AdminUserResponse.from_orm_user(user)

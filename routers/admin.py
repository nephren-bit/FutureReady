"""
routers/admin.py

Account administration — row 11 of the Project 1 report's permission matrix
("Quản lý tài khoản và phân quyền"), reachable only by AC-04 Quản trị viên.

Every route here depends on `require_admin`, so a learner's or lecturer's
token gets 403 and an absent token gets 401, per NFR-08.

Two rules this module holds
---------------------------
**Disabling is not deleting.** Locking an account flips `is_active`; no row is
removed. The session history hanging off `analysis_sessions` stays intact and
still attributable, which is the whole reason the account existed. A DELETE
would take the evidence with it.

**Administrators are not made here.** There is no endpoint to grant
`is_admin`, and `AdminUpdateUserRequest` has no such field. Admin rights come
only from `scripts/create_admin.py`, run at the machine. This is what keeps a
single compromised administrator session from quietly minting more
administrators — the blast radius stops at what one account can do, and does
not extend to creating new ones.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from db.models import AnalysisSession, UserORM, UserRole
from models.auth_models import (
    AdminStatsResponse,
    AdminUpdateUserRequest,
    UserListResponse,
    UserPublic,
)
from routers.dependencies import CurrentAdmin, DbDep
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["Administration"])


def _get_user_or_404(db: DbDep, user_id: uuid.UUID) -> UserORM:
    """Fetch an account or raise 404."""
    user = db.get(UserORM, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản này."
        )
    return user


@router.get("/users", response_model=UserListResponse, summary="Danh sách và tìm kiếm tài khoản.")
def list_users(
    admin: CurrentAdmin,
    db: DbDep,
    search: str | None = Query(None, description="Tìm theo email hoặc họ tên (không phân biệt hoa thường)."),
    role: UserRole | None = Query(None, description="Lọc theo vai trò."),
    is_active: bool | None = Query(None, description="Lọc theo trạng thái khoá."),
    is_admin: bool | None = Query(None, description="Chỉ lấy quản trị viên."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> UserListResponse:
    """
    One page of accounts, with the filters the admin screen offers.

    `total` counts every match *before* paging, so the UI can show "1-50 of
    312" rather than only knowing how many rows it happened to receive.
    """
    filters = []
    if search:
        pattern = f"%{search.strip().lower()}%"
        filters.append(
            or_(func.lower(UserORM.email).like(pattern), func.lower(UserORM.full_name).like(pattern))
        )
    if role is not None:
        filters.append(UserORM.role == role)
    if is_active is not None:
        filters.append(UserORM.is_active.is_(is_active))
    if is_admin is not None:
        filters.append(UserORM.is_admin.is_(is_admin))

    total = db.scalar(select(func.count(UserORM.id)).where(*filters)) or 0
    rows = db.scalars(
        select(UserORM)
        .where(*filters)
        .order_by(UserORM.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return UserListResponse(total=total, items=[UserPublic.model_validate(r) for r in rows])


@router.get("/users/{user_id}", response_model=UserPublic, summary="Chi tiết một tài khoản.")
def get_user(user_id: uuid.UUID, admin: CurrentAdmin, db: DbDep) -> UserPublic:
    """One account's detail."""
    return UserPublic.model_validate(_get_user_or_404(db, user_id))


@router.patch(
    "/users/{user_id}",
    response_model=UserPublic,
    summary="Đổi vai trò, đánh dấu đã xác minh, khoá hoặc mở khoá tài khoản.",
)
def update_user(
    user_id: uuid.UUID, payload: AdminUpdateUserRequest, admin: CurrentAdmin, db: DbDep
) -> UserPublic:
    """
    Apply an administrator's changes to one account.

    Two guards, both about an administrator not being able to strand the
    instance or themselves:

    * An administrator cannot lock their own account. Doing so would log them
      out mid-action with no way back in short of the CLI, and it is far more
      likely to be a misclick on the wrong row than an intention.
    * Another administrator's account cannot be locked from here either.
      Admin rights are granted only at the machine, so they should only be
      taken away there too — otherwise one administrator can unilaterally shut
      out all the others.
    """
    user = _get_user_or_404(db, user_id)

    if payload.is_active is False:
        if user.id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tự khoá tài khoản của chính mình.",
            )
        if user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Không khoá được tài khoản quản trị viên từ giao diện. "
                    "Quyền quản trị chỉ cấp và thu hồi bằng lệnh tại máy chủ."
                ),
            )

    changes: list[str] = []
    if payload.role is not None and payload.role != user.role:
        changes.append(f"role {user.role.value} -> {payload.role.value}")
        user.role = payload.role
    if payload.is_verified is not None and payload.is_verified != user.is_verified:
        changes.append(f"is_verified -> {payload.is_verified}")
        user.is_verified = payload.is_verified
    if payload.is_active is not None and payload.is_active != user.is_active:
        changes.append(f"is_active -> {payload.is_active}")
        user.is_active = payload.is_active

    if changes:
        db.commit()
        db.refresh(user)
        logger.info("Admin %s updated account %s: %s", admin.id, user.id, "; ".join(changes))

    return UserPublic.model_validate(user)


@router.get("/stats", response_model=AdminStatsResponse, summary="Số liệu tổng quan.")
def get_stats(admin: CurrentAdmin, db: DbDep) -> AdminStatsResponse:
    """Headline counts for the admin dashboard."""

    def count(*conditions) -> int:
        return db.scalar(select(func.count(UserORM.id)).where(*conditions)) or 0

    return AdminStatsResponse(
        total_users=count(),
        active_users=count(UserORM.is_active.is_(True)),
        inactive_users=count(UserORM.is_active.is_(False)),
        verified_users=count(UserORM.is_verified.is_(True)),
        # Counted excluding admins so the three figures partition the user
        # base instead of double-counting an administrator under their role.
        learners=count(UserORM.role == UserRole.LEARNER, UserORM.is_admin.is_(False)),
        lecturers=count(UserORM.role == UserRole.LECTURER, UserORM.is_admin.is_(False)),
        admins=count(UserORM.is_admin.is_(True)),
        total_sessions=db.scalar(select(func.count(AnalysisSession.id))) or 0,
    )

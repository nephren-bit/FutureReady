"""
routers/auth.py

Registration, sign-in, profile, password, and self-service role switching —
rows 1 to 3 of the Project 1 report's permission matrix (Bang 3.3).

Registration admits the user immediately. There is no approval queue, and the
report is explicit about why: at this stage the administrators *are* the
development team, and the team has no way to verify that someone claiming to
be a lecturer really is one. A manual review that cannot actually check
anything adds delay and produces a false sense of assurance, so `is_verified`
exists as a separate flag an institution can set later, and it does not gate
sign-in.

What this router refuses to do
------------------------------
No endpoint here can grant administrator rights. `UserRole` has no `admin`
value, so `POST /auth/register` and `PATCH /auth/me/role` cannot mint one
even if a caller sends `{"role": "admin"}` — the request fails schema
validation before any handler runs. Administrators are created only by
`scripts/create_admin.py`, at the machine, by someone with database access.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from config import settings
from db.models import UserORM
from models.auth_models import (
    ChangePasswordRequest,
    ChangeRoleRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserPublic,
)
from routers.dependencies import CurrentUser, DbDep
from utils.logger import get_logger
from utils.security import PasswordTooLongError, create_access_token, hash_password, verify_password

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# A real bcrypt hash of a value nobody will ever submit, used to spend the
# same time on a sign-in for an address that has no account as on one that
# does. Computed once at import so it costs nothing per request.
_TIMING_EQUALIZER_HASH = hash_password("khong-phai-mat-khau-cua-ai-ca")


def _normalize_email(email: str) -> str:
    """
    Emails are compared and stored lowercased.

    Without this, `An@truong.edu.vn` and `an@truong.edu.vn` register as two
    accounts that every human reader would take for one, and the person who
    made the second one can never work out why their password is "wrong".
    """
    return email.strip().lower()


def _issue_token(user: UserORM) -> TokenResponse:
    """Build the register/login response for an account."""
    token = create_access_token(user.id, role=user.role.value, is_admin=user.is_admin)
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
        user=UserPublic.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký tài khoản mới và đăng nhập ngay.",
)
def register(payload: RegisterRequest, db: DbDep) -> TokenResponse:
    """
    Create an account and return a token for it, so the user lands signed in
    rather than being bounced to a login form they just filled in.
    """
    email = _normalize_email(payload.email)

    if db.scalar(select(UserORM).where(UserORM.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email này đã được đăng ký. Hãy đăng nhập hoặc dùng email khác.",
        )

    try:
        password_hash = hash_password(payload.password)
    except PasswordTooLongError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    user = UserORM(
        email=email,
        password_hash=password_hash,
        full_name=payload.full_name.strip(),
        role=payload.role,
        preferred_language=payload.preferred_language,
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("Registered account %s with role %s.", user.id, user.role.value)
    return _issue_token(user)


@router.post("/login", response_model=TokenResponse, summary="Đăng nhập.")
def login(payload: LoginRequest, db: DbDep) -> TokenResponse:
    """
    Verify credentials and issue an access token.

    Every failure returns the same message and the same status. Saying "no
    such email" would turn this endpoint into a way to enumerate who has an
    account, which is worth more to an attacker than it is to a user who
    mistyped.
    """
    email = _normalize_email(payload.email)
    user = db.scalar(select(UserORM).where(UserORM.email == email))

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email hoặc mật khẩu không đúng.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None or user.password_hash is None:
        # Hash against a throwaway value anyway. Returning immediately would
        # make "no such account" answer in microseconds while a real account
        # with a wrong password takes the ~quarter second bcrypt costs, and
        # that gap alone tells an attacker which addresses are registered --
        # exactly what the identical error message above is meant to hide.
        verify_password(payload.password, _TIMING_EQUALIZER_HASH)
        raise invalid
    if not verify_password(payload.password, user.password_hash):
        logger.info("Failed sign-in attempt for %s.", email)
        raise invalid
    if not user.is_active:
        # Distinguished from bad credentials on purpose: the password was
        # right, and telling this person to keep retrying it would be a lie.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khoá. Liên hệ quản trị viên để mở khoá.",
        )

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    logger.info("Account %s signed in.", user.id)
    return _issue_token(user)


@router.get("/me", response_model=UserPublic, summary="Thông tin tài khoản đang đăng nhập.")
def read_me(user: CurrentUser) -> UserPublic:
    """Who the caller is, as the client should render them."""
    return UserPublic.model_validate(user)


@router.patch("/me", response_model=UserPublic, summary="Cập nhật hồ sơ cá nhân.")
def update_me(payload: UpdateProfileRequest, user: CurrentUser, db: DbDep) -> UserPublic:
    """
    Update the caller's own profile.

    Email is not editable here — it is the sign-in identity, and changing it
    needs a confirmation flow this milestone does not have.
    """
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.preferred_language is not None:
        user.preferred_language = payload.preferred_language

    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)


@router.patch(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    # Explicit, because a `-> None` return annotation alone still makes
    # FastAPI build a JSON response model, which a 204 may not carry.
    response_class=Response,
    summary="Đổi mật khẩu.",
)
def change_password(payload: ChangePasswordRequest, user: CurrentUser, db: DbDep) -> Response:
    """
    Change the caller's password, current password required.

    Being signed in is not enough: a token left behind on a shared machine
    should not be sufficient to lock the real owner out of their account.
    """
    if user.password_hash is None or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Mật khẩu hiện tại không đúng."
        )

    try:
        user.password_hash = hash_password(payload.new_password)
    except PasswordTooLongError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    db.commit()
    logger.info("Account %s changed its password.", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/me/role", response_model=UserPublic, summary="Đổi vai trò trong cài đặt.")
def change_role(payload: ChangeRoleRequest, user: CurrentUser, db: DbDep) -> UserPublic:
    """
    Switch between learner and lecturer.

    Only the `role` column is written, so nothing hanging off the account is
    touched: session history, reports, and practice attempts all survive the
    switch, and switching back restores the previous view of them exactly.

    A new token is *not* issued here. The caller keeps the old one until it
    expires, so the client should call `/auth/login` again — or simply read
    `/auth/me` — to pick the change up. The alternative, silently returning a
    fresh token from a PATCH, hides a credential rotation inside an update.
    """
    previous = user.role
    user.role = payload.role
    db.commit()
    db.refresh(user)

    logger.info("Account %s changed role: %s -> %s.", user.id, previous.value, user.role.value)
    return UserPublic.model_validate(user)


@router.post(
    "/me/recording-consent",
    response_model=UserPublic,
    summary="Xác nhận trách nhiệm thông báo cho người bị ghi hình.",
)
def acknowledge_recording_consent(user: CurrentUser, db: DbDep) -> UserPublic:
    """
    Record that this account accepted responsibility for telling the people
    they record that they are being recorded.

    Deliberately at the account layer only as a *record* of the
    acknowledgement. The protection that actually works lives at the
    recording layer — the person being filmed knowing about it — and a role
    label has never stopped anyone from filming someone else.
    """
    if user.recording_consent_ack_at is None:
        user.recording_consent_ack_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        logger.info("Account %s acknowledged the recording notice.", user.id)
    return UserPublic.model_validate(user)


@router.get("/exists", summary="Kiểm tra hệ thống đã có tài khoản nào chưa.")
def any_account_exists(db: DbDep) -> dict[str, bool]:
    """
    Whether the instance has any account at all.

    Lets a fresh deployment show first-run setup instructions instead of a
    sign-in form nobody can yet satisfy. Returns a single boolean and no
    identifying detail, so it is safe to leave unauthenticated.
    """
    return {"any_account": bool(db.scalar(select(func.count(UserORM.id))))}

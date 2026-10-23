from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import get_current_user, get_db, get_settings
from ..i18n import AppError
from ..models import Role, User, UserStatus
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)) -> User:
    # Admins are provisioned by configuration, never through self-registration.
    if data.role is Role.admin:
        raise AppError(403, "auth.forbidden")
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError(409, "auth.email_taken")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        role=data.role,
        language=data.language,
    )
    db.add(user)
    db.commit()
    return user


@router.post("/login", response_model=TokenOut)
def login(
    data: LoginIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> TokenOut:
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise AppError(401, "auth.invalid_credentials")
    if user.status is UserStatus.suspended:
        raise AppError(403, "auth.suspended")
    return TokenOut(
        access_token=create_token(user.id, settings.secret_key, settings.token_ttl_seconds)
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user

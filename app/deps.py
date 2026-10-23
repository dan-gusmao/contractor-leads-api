"""FastAPI dependencies: DB session, settings, and the authenticated user."""

from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings
from .i18n import AppError
from .models import Role, User, UserStatus
from .payments import PaymentProvider
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_payment_provider(request: Request) -> PaymentProvider:
    return request.app.state.payment_provider


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    if credentials is None:
        return None
    user_id = decode_token(credentials.credentials, settings.secret_key)
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise AppError(401, "auth.invalid_token")
    if user.status is UserStatus.suspended:
        raise AppError(403, "auth.suspended")
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise AppError(401, "auth.not_authenticated")
    return user


def require_role(*roles: Role) -> Callable[..., User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError(403, "auth.forbidden")
        return user

    return dependency


require_customer = require_role(Role.customer)
require_contractor = require_role(Role.contractor)
require_admin = require_role(Role.admin)

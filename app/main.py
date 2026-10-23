"""Application factory."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .config import Settings
from .db import Base, make_engine, make_session_factory
from .i18n import AppError, resolve_language, translate
from .models import Role, User
from .payments import FakePaymentProvider, PaymentProvider
from .routers import admin, auth, credits, messages, profiles, projects, reviews
from .security import hash_password


def _bootstrap_admin(app: FastAPI, settings: Settings) -> None:
    """Create the configured admin account if it does not exist yet."""
    if not (settings.admin_email and settings.admin_password):
        return
    with app.state.session_factory() as db:
        email = settings.admin_email.lower()
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(email=email, password_hash=hash_password(settings.admin_password), role=Role.admin))
            db.commit()


def create_app(
    settings: Settings | None = None, payment_provider: PaymentProvider | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Contractor Leads API", version="0.1.0")

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.payment_provider = payment_provider or FakePaymentProvider(
        settings.payment_webhook_secret
    )
    _bootstrap_admin(app, settings)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        lang = resolve_language(request)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": translate(exc.code, lang, **exc.params)}},
        )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    for module in (auth, profiles, projects, credits, messages, reviews, admin):
        app.include_router(module.router)

    return app

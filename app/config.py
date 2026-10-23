"""Application settings and business configuration.

Values that the roadmap leaves for the business to confirm (categories,
credit packages, unlock price) live here so they can change without code
changes elsewhere.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CreditPackage:
    id: str
    credits: int
    price_cents: int
    currency: str = "EUR"


#: Project categories with English and Finnish labels.
CATEGORIES: dict[str, dict[str, str]] = {
    "renovation": {"en": "Renovation", "fi": "Remontti"},
    "construction": {"en": "Construction", "fi": "Rakentaminen"},
    "maintenance": {"en": "Maintenance", "fi": "Huolto"},
    "plumbing": {"en": "Plumbing", "fi": "Putkityöt"},
    "electrical": {"en": "Electrical", "fi": "Sähkötyöt"},
    "painting": {"en": "Painting", "fi": "Maalaus"},
    "roofing": {"en": "Roofing", "fi": "Kattotyöt"},
}

DEFAULT_PACKAGES = (
    CreditPackage("starter", credits=10, price_cents=4900),
    CreditPackage("pro", credits=30, price_cents=12900),
    CreditPackage("business", credits=100, price_cents=37900),
)


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./leads.db"
    secret_key: str = "dev-secret-change-me"
    token_ttl_seconds: int = 60 * 60 * 24
    payment_webhook_secret: str = "dev-webhook-secret"
    unlock_cost: int = 1
    media_dir: str = "./media"
    max_images_per_project: int = 5
    max_image_bytes: int = 5 * 1024 * 1024
    admin_email: str | None = None
    admin_password: str | None = None
    credit_packages: tuple[CreditPackage, ...] = field(default=DEFAULT_PACKAGES)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            database_url=env.get("LEADS_DATABASE_URL", cls.database_url),
            secret_key=env.get("LEADS_SECRET_KEY", cls.secret_key),
            payment_webhook_secret=env.get(
                "LEADS_PAYMENT_WEBHOOK_SECRET", cls.payment_webhook_secret
            ),
            unlock_cost=int(env.get("LEADS_UNLOCK_COST", cls.unlock_cost)),
            media_dir=env.get("LEADS_MEDIA_DIR", cls.media_dir),
            admin_email=env.get("LEADS_ADMIN_EMAIL"),
            admin_password=env.get("LEADS_ADMIN_PASSWORD"),
        )

    def package(self, package_id: str) -> CreditPackage | None:
        return next((p for p in self.credit_packages if p.id == package_id), None)

"""Request and response models."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from .models import PaymentStatus, ProjectStatus, ReviewStatus, Role, TransactionKind, UserStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role
    language: str = Field(default="en", pattern="^(en|fi)$")


class LoginIn(BaseModel):
    # Plain str: a malformed email should fail as bad credentials, not as a 422.
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: str
    role: Role
    status: UserStatus
    language: str
    created_at: datetime


# --- profiles ---------------------------------------------------------------


class CustomerProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=100)


class CustomerProfileOut(ORMModel):
    full_name: str
    phone: str | None
    city: str | None


class ContractorProfileIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    business_id: str | None = Field(default=None, description="Optional Finnish Y-tunnus")
    description: str | None = Field(default=None, max_length=5000)
    services: list[str] = Field(default_factory=list)
    service_area: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=255)


class ContractorProfileOut(BaseModel):
    company_name: str
    business_id: str | None
    description: str | None
    services: list[str]
    service_area: str | None
    phone: str | None
    website: str | None
    credit_balance: int


class PublicContractorOut(BaseModel):
    """What anyone can see. Trust signals only, no credit data."""

    user_id: int
    company_name: str
    business_id: str | None
    has_business_id: bool
    description: str | None
    services: list[str]
    service_area: str | None
    website: str | None
    member_since: datetime
    review_count: int
    average_rating: float | None
    reviews: list["ReviewOut"]


# --- projects ---------------------------------------------------------------


class ProjectIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=10000)
    category: str
    location: str = Field(min_length=2, max_length=200)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr
    contact_phone: str | None = Field(default=None, max_length=50)


class ProjectUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=10000)
    category: str | None = None
    location: str | None = Field(default=None, min_length=2, max_length=200)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    contact_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)


class ContactOut(BaseModel):
    name: str
    email: str
    phone: str | None


class ImageOut(BaseModel):
    id: int
    url: str
    content_type: str


class ProjectOut(BaseModel):
    id: int
    title: str
    description: str
    category: str
    category_label: str
    location: str
    budget_min: int | None
    budget_max: int | None
    status: ProjectStatus
    created_at: datetime
    images: list[ImageOut]
    unlock_cost: int
    contact_locked: bool
    contact: ContactOut | None
    rejection_reason: str | None = None


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    total: int
    limit: int
    offset: int


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


# --- credits & payments -----------------------------------------------------


class CreditPackageOut(BaseModel):
    id: str
    credits: int
    price_cents: int
    currency: str


class UnlockOut(BaseModel):
    project_id: int
    credits_spent: int
    charged: bool
    credit_balance: int
    contact: ContactOut
    unlocked_at: datetime


class UnlockedProjectOut(BaseModel):
    project: ProjectOut
    credits_spent: int
    unlocked_at: datetime


class TransactionOut(ORMModel):
    id: int
    contractor_id: int
    kind: TransactionKind
    amount: int
    balance_after: int
    reason: str | None
    project_id: int | None
    payment_id: int | None
    admin_id: int | None
    created_at: datetime


class CheckoutIn(BaseModel):
    package_id: str


class PaymentOut(ORMModel):
    id: int
    contractor_id: int
    package_id: str
    credits: int
    amount_cents: int
    currency: str
    provider: str
    provider_reference: str
    status: PaymentStatus
    created_at: datetime
    completed_at: datetime | None


class CheckoutOut(BaseModel):
    payment: PaymentOut
    checkout_url: str


class CreditAdjustIn(BaseModel):
    amount: int = Field(description="Positive to add credits, negative to remove them")
    reason: str = Field(min_length=3, max_length=500)


# --- messaging & reviews ----------------------------------------------------


MessageBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class MessageIn(BaseModel):
    body: MessageBody


class StartConversationIn(BaseModel):
    contractor_id: int | None = Field(
        default=None, description="Required when a customer starts the conversation"
    )
    body: MessageBody


class MessageOut(ORMModel):
    id: int
    sender_id: int
    body: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    project_id: int
    project_title: str
    customer_id: int
    contractor_id: int
    last_message_at: datetime | None
    messages: list[MessageOut]


class ReviewIn(BaseModel):
    contractor_id: int
    project_id: int
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=5000)


class ReviewOut(ORMModel):
    id: int
    customer_id: int
    contractor_id: int
    project_id: int
    rating: int
    comment: str | None
    status: ReviewStatus
    created_at: datetime


class UserStatusIn(BaseModel):
    status: UserStatus


class ReviewStatusIn(BaseModel):
    status: ReviewStatus


class ReportOut(BaseModel):
    customers: int
    contractors: int
    projects_submitted: int
    projects_approved: int
    projects_published: int
    contact_unlocks: int
    credits_purchased: int
    credits_manually_assigned: int
    credits_used: int
    messages_sent: int
    reviews_submitted: int
    revenue_cents: int


PublicContractorOut.model_rebuild()

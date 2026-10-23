"""Marketplace metrics listed in the roadmap (Phase 9)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ContactUnlock,
    CreditTransaction,
    Message,
    Payment,
    PaymentStatus,
    Project,
    ProjectStatus,
    Review,
    Role,
    TransactionKind,
    User,
)
from ..schemas import ReportOut


def _count(db: Session, statement) -> int:
    return db.scalar(select(func.count()).select_from(statement.subquery())) or 0


def _credit_sum(db: Session, *kinds: TransactionKind, positive: bool | None = None) -> int:
    query = select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
        CreditTransaction.kind.in_(kinds)
    )
    if positive is True:
        query = query.where(CreditTransaction.amount > 0)
    return db.scalar(query)


def marketplace_report(db: Session) -> ReportOut:
    return ReportOut(
        customers=_count(db, select(User.id).where(User.role == Role.customer)),
        contractors=_count(db, select(User.id).where(User.role == Role.contractor)),
        # "Submitted" counts every project that has ever been sent for review.
        projects_submitted=_count(db, select(Project.id).where(Project.submitted_at.is_not(None))),
        projects_approved=_count(db, select(Project.id).where(Project.approved_at.is_not(None))),
        projects_published=_count(
            db, select(Project.id).where(Project.status == ProjectStatus.published)
        ),
        contact_unlocks=_count(db, select(ContactUnlock.id)),
        credits_purchased=_credit_sum(db, TransactionKind.purchase),
        credits_manually_assigned=_credit_sum(
            db, TransactionKind.admin_grant, TransactionKind.admin_adjustment, positive=True
        ),
        credits_used=-_credit_sum(db, TransactionKind.unlock),
        messages_sent=_count(db, select(Message.id)),
        reviews_submitted=_count(db, select(Review.id)),
        revenue_cents=db.scalar(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.status == PaymentStatus.paid
            )
        ),
    )

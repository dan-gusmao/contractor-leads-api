from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import get_db, get_settings, require_admin
from ..i18n import AppError, resolve_language
from ..models import (
    ContactUnlock,
    CreditTransaction,
    Payment,
    Project,
    ProjectStatus,
    Review,
    ReviewStatus,
    Role,
    TransactionKind,
    User,
)
from ..schemas import (
    CreditAdjustIn,
    PaymentOut,
    ProjectOut,
    RejectIn,
    ReportOut,
    ReviewOut,
    ReviewStatusIn,
    TransactionOut,
    UserOut,
    UserStatusIn,
)
from ..services.credits import change_balance, contractor_profile
from ..services.presenters import project_out
from ..services.reports import marketplace_report

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# --- users ------------------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(role: Role | None = None, db: Session = Depends(get_db)) -> list[User]:
    query = select(User).order_by(User.id)
    if role is not None:
        query = query.where(User.role == role)
    return list(db.scalars(query))


@router.patch("/users/{user_id}/status", response_model=UserOut)
def set_user_status(
    user_id: int,
    data: UserStatusIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "user.not_found")
    if user.id == admin.id:
        # An admin cannot lock themself out.
        raise AppError(403, "auth.forbidden")
    user.status = data.status
    db.commit()
    return user


# --- project moderation -----------------------------------------------------


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    request: Request,
    status: ProjectStatus | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ProjectOut]:
    query = select(Project).order_by(Project.submitted_at.is_(None), Project.submitted_at, Project.id)
    if status is not None:
        query = query.where(Project.status == status)
    lang = resolve_language(request)
    return [project_out(db, p, admin, lang, settings.unlock_cost) for p in db.scalars(query)]


def _moderate(
    db: Session, project_id: int, allowed: set[ProjectStatus], target: ProjectStatus, action: str
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project.not_found")
    if project.status not in allowed:
        raise AppError(
            409, "project.invalid_transition", status=project.status.value, action=action
        )
    project.status = target
    return project


@router.post("/projects/{project_id}/approve", response_model=ProjectOut)
def approve_project(
    project_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    project = _moderate(
        db, project_id, {ProjectStatus.submitted}, ProjectStatus.published, "approved"
    )
    project.approved_at = datetime.now(UTC)
    project.rejection_reason = None
    db.commit()
    return project_out(db, project, admin, resolve_language(request), settings.unlock_cost)


@router.post("/projects/{project_id}/reject", response_model=ProjectOut)
def reject_project(
    project_id: int,
    data: RejectIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    project = _moderate(
        db, project_id, {ProjectStatus.submitted}, ProjectStatus.rejected, "rejected"
    )
    project.rejection_reason = data.reason
    db.commit()
    return project_out(db, project, admin, resolve_language(request), settings.unlock_cost)


@router.post("/projects/{project_id}/remove", response_model=ProjectOut)
def remove_project(
    project_id: int,
    data: RejectIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    """Take down an inappropriate project. Existing unlocks keep their contact access."""
    project = _moderate(
        db,
        project_id,
        {ProjectStatus.submitted, ProjectStatus.published, ProjectStatus.rejected},
        ProjectStatus.removed,
        "removed",
    )
    project.rejection_reason = data.reason
    db.commit()
    return project_out(db, project, admin, resolve_language(request), settings.unlock_cost)


# --- review moderation ------------------------------------------------------


@router.get("/reviews", response_model=list[ReviewOut])
def list_reviews(status: ReviewStatus | None = None, db: Session = Depends(get_db)) -> list[Review]:
    query = select(Review).order_by(Review.id.desc())
    if status is not None:
        query = query.where(Review.status == status)
    return list(db.scalars(query))


@router.patch("/reviews/{review_id}", response_model=ReviewOut)
def set_review_status(
    review_id: int, data: ReviewStatusIn, db: Session = Depends(get_db)
) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise AppError(404, "review.not_found")
    review.status = data.status
    db.commit()
    return review


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review(review_id: int, db: Session = Depends(get_db)) -> None:
    review = db.get(Review, review_id)
    if review is None:
        raise AppError(404, "review.not_found")
    db.delete(review)
    db.commit()


# --- credits & payments -----------------------------------------------------


@router.post("/contractors/{user_id}/credits", response_model=TransactionOut, status_code=201)
def adjust_credits(
    user_id: int,
    data: CreditAdjustIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CreditTransaction:
    """Grant credits (positive amount) or correct a balance (negative amount)."""
    if data.amount == 0:
        raise AppError(422, "validation.invalid_amount")
    contractor = db.get(User, user_id)
    if contractor is None or contractor.role is not Role.contractor:
        raise AppError(404, "contractor.not_found")
    contractor_profile(db, contractor)

    kind = TransactionKind.admin_grant if data.amount > 0 else TransactionKind.admin_adjustment
    try:
        change_balance(db, contractor.id, data.amount, kind, reason=data.reason, admin_id=admin.id)
        db.commit()
    except AppError:
        db.rollback()
        raise
    return db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.contractor_id == contractor.id)
        .order_by(CreditTransaction.id.desc())
    ).first()


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    contractor_id: int | None = None,
    kind: TransactionKind | None = None,
    db: Session = Depends(get_db),
) -> list[CreditTransaction]:
    query = select(CreditTransaction).order_by(CreditTransaction.id.desc())
    if contractor_id is not None:
        query = query.where(CreditTransaction.contractor_id == contractor_id)
    if kind is not None:
        query = query.where(CreditTransaction.kind == kind)
    return list(db.scalars(query))


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(db: Session = Depends(get_db)) -> list[Payment]:
    return list(db.scalars(select(Payment).order_by(Payment.id.desc())))


@router.get("/unlocks")
def list_unlocks(
    contractor_id: int | None = None, project_id: int | None = None, db: Session = Depends(get_db)
) -> list[dict]:
    query = select(ContactUnlock).order_by(ContactUnlock.id.desc())
    if contractor_id is not None:
        query = query.where(ContactUnlock.contractor_id == contractor_id)
    if project_id is not None:
        query = query.where(ContactUnlock.project_id == project_id)
    return [
        {
            "id": u.id,
            "contractor_id": u.contractor_id,
            "project_id": u.project_id,
            "credits_spent": u.credits_spent,
            "created_at": u.created_at,
        }
        for u in db.scalars(query)
    ]


@router.get("/reports", response_model=ReportOut)
def reports(db: Session = Depends(get_db)) -> ReportOut:
    return marketplace_report(db)

"""Credit ledger and contact unlocking.

Business rules (roadmap, Phase 5):
- a contractor pays only once per project contact;
- any number of contractors may unlock the same project;
- unlocked contact information stays available permanently.
"""

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..i18n import AppError
from ..models import (
    ContactUnlock,
    ContractorProfile,
    CreditTransaction,
    Project,
    ProjectStatus,
    TransactionKind,
    User,
)


@dataclass
class UnlockResult:
    unlock: ContactUnlock
    charged: bool
    balance: int


def contractor_profile(db: Session, contractor: User) -> ContractorProfile:
    profile = db.scalar(select(ContractorProfile).where(ContractorProfile.user_id == contractor.id))
    if profile is None:
        raise AppError(409, "profile.missing")
    return profile


def find_unlock(db: Session, contractor_id: int, project_id: int) -> ContactUnlock | None:
    return db.scalar(
        select(ContactUnlock).where(
            ContactUnlock.contractor_id == contractor_id,
            ContactUnlock.project_id == project_id,
        )
    )


def change_balance(
    db: Session,
    contractor_id: int,
    amount: int,
    kind: TransactionKind,
    *,
    reason: str | None = None,
    project_id: int | None = None,
    payment_id: int | None = None,
    admin_id: int | None = None,
) -> int:
    """Apply ``amount`` to the balance and record it in the ledger.

    The guarded UPDATE makes the balance check and the change one atomic
    step, so concurrent spends cannot push the balance below zero. The caller
    owns the transaction (commit/rollback).
    """
    result = db.execute(
        update(ContractorProfile)
        .where(
            ContractorProfile.user_id == contractor_id,
            ContractorProfile.credit_balance + amount >= 0,
        )
        .values(credit_balance=ContractorProfile.credit_balance + amount)
        .returning(ContractorProfile.credit_balance)
    )
    new_balance = result.scalar_one_or_none()
    if new_balance is None:
        current = db.scalar(
            select(ContractorProfile.credit_balance).where(
                ContractorProfile.user_id == contractor_id
            )
        )
        if current is None:
            raise AppError(409, "profile.missing")
        if kind is TransactionKind.unlock:
            raise AppError(402, "credits.insufficient", required=-amount, available=current)
        raise AppError(409, "credits.negative_balance")

    db.add(
        CreditTransaction(
            contractor_id=contractor_id,
            kind=kind,
            amount=amount,
            balance_after=new_balance,
            reason=reason,
            project_id=project_id,
            payment_id=payment_id,
            admin_id=admin_id,
        )
    )
    return new_balance


def unlock_contact(db: Session, contractor: User, project: Project, cost: int) -> UnlockResult:
    profile = contractor_profile(db, contractor)

    existing = find_unlock(db, contractor.id, project.id)
    if existing is not None:
        return UnlockResult(existing, charged=False, balance=profile.credit_balance)

    if project.status is not ProjectStatus.published:
        raise AppError(409, "project.not_public")
    if project.customer_id == contractor.id:
        raise AppError(409, "credits.own_project")

    try:
        balance = change_balance(
            db, contractor.id, -cost, TransactionKind.unlock, project_id=project.id
        )
        unlock = ContactUnlock(contractor_id=contractor.id, project_id=project.id, credits_spent=cost)
        db.add(unlock)
        db.commit()
    except IntegrityError:
        # A concurrent request unlocked the same project first; it paid, we don't.
        db.rollback()
        existing = find_unlock(db, contractor.id, project.id)
        db.refresh(profile)
        return UnlockResult(existing, charged=False, balance=profile.credit_balance)
    except AppError:
        db.rollback()
        raise

    return UnlockResult(unlock, charged=True, balance=balance)

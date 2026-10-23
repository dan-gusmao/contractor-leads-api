from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import get_db, get_payment_provider, get_settings, require_contractor
from ..i18n import AppError
from ..models import CreditTransaction, Payment, PaymentStatus, TransactionKind, User
from ..payments import PaymentProvider
from ..schemas import CheckoutIn, CheckoutOut, CreditPackageOut, PaymentOut, TransactionOut
from ..services.credits import change_balance, contractor_profile

router = APIRouter(tags=["credits"])


@router.get("/credits/packages", response_model=list[CreditPackageOut])
def list_packages(settings: Settings = Depends(get_settings)) -> list[CreditPackageOut]:
    return [CreditPackageOut(**vars(p)) for p in settings.credit_packages]


@router.get("/me/credits")
def my_credits(user: User = Depends(require_contractor), db: Session = Depends(get_db)) -> dict:
    profile = contractor_profile(db, user)
    transactions = db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.contractor_id == user.id)
        .order_by(CreditTransaction.id.desc())
    ).all()
    return {
        "credit_balance": profile.credit_balance,
        "transactions": [TransactionOut.model_validate(t) for t in transactions],
    }


@router.post("/credits/checkout", response_model=CheckoutOut, status_code=201)
def start_checkout(
    data: CheckoutIn,
    user: User = Depends(require_contractor),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider: PaymentProvider = Depends(get_payment_provider),
) -> CheckoutOut:
    contractor_profile(db, user)
    package = settings.package(data.package_id)
    if package is None:
        raise AppError(404, "payment.unknown_package", package_id=data.package_id)

    session = provider.create_checkout(
        package.price_cents, package.currency, f"Contractor Leads {package.credits} credits"
    )
    payment = Payment(
        contractor_id=user.id,
        package_id=package.id,
        credits=package.credits,
        amount_cents=package.price_cents,
        currency=package.currency,
        provider=provider.name,
        provider_reference=session.reference,
        status=PaymentStatus.pending,
    )
    db.add(payment)
    db.commit()
    return CheckoutOut(payment=PaymentOut.model_validate(payment), checkout_url=session.checkout_url)


@router.get("/me/payments", response_model=list[PaymentOut])
def my_payments(user: User = Depends(require_contractor), db: Session = Depends(get_db)) -> list[Payment]:
    return list(
        db.scalars(
            select(Payment).where(Payment.contractor_id == user.id).order_by(Payment.id.desc())
        ).all()
    )


@router.post("/payments/webhook")
async def payment_webhook(
    request: Request,
    x_payment_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
    provider: PaymentProvider = Depends(get_payment_provider),
) -> dict:
    event = provider.parse_webhook(await request.body(), x_payment_signature)
    if event is None:
        raise AppError(400, "payment.invalid_signature")

    payment = db.scalar(select(Payment).where(Payment.provider_reference == event.reference))
    if payment is None:
        raise AppError(404, "payment.not_found")

    # Providers retry notifications; only the first one for a pending payment
    # counts. The conditional UPDATE claims the payment atomically, so two
    # concurrent deliveries cannot both credit the contractor.
    new_status = PaymentStatus.paid if event.status == "paid" else PaymentStatus.failed
    claimed = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == PaymentStatus.pending)
        .values(status=new_status, completed_at=datetime.now(UTC))
    ).rowcount
    if not claimed:
        db.rollback()
        db.refresh(payment)
        return {"status": payment.status.value, "duplicate": True}

    if new_status is PaymentStatus.paid:
        change_balance(
            db,
            payment.contractor_id,
            payment.credits,
            TransactionKind.purchase,
            payment_id=payment.id,
            reason=f"Package {payment.package_id}",
        )
    db.commit()
    return {"status": new_status.value, "duplicate": False}

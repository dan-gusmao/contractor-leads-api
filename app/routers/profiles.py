from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import CATEGORIES
from ..deps import get_db, require_contractor, require_customer
from ..i18n import AppError
from ..models import ContractorProfile, CustomerProfile, Role, User, UserStatus
from ..schemas import (
    ContractorProfileIn,
    ContractorProfileOut,
    CustomerProfileIn,
    CustomerProfileOut,
    PublicContractorOut,
)
from ..services.presenters import public_contractor_out, split_services
from ..validators import is_valid_business_id

router = APIRouter(tags=["profiles"])


# --- customer ---------------------------------------------------------------


def _customer_profile(db: Session, user: User) -> CustomerProfile:
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if profile is None:
        raise AppError(404, "profile.missing")
    return profile


@router.get("/me/customer-profile", response_model=CustomerProfileOut)
def get_customer_profile(
    user: User = Depends(require_customer), db: Session = Depends(get_db)
) -> CustomerProfile:
    return _customer_profile(db, user)


@router.put("/me/customer-profile", response_model=CustomerProfileOut)
def upsert_customer_profile(
    data: CustomerProfileIn,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
) -> CustomerProfile:
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if profile is None:
        profile = CustomerProfile(user_id=user.id, **data.model_dump())
        db.add(profile)
    else:
        for key, value in data.model_dump().items():
            setattr(profile, key, value)
    db.commit()
    return profile


# --- contractor -------------------------------------------------------------


def _contractor_out(profile: ContractorProfile) -> ContractorProfileOut:
    return ContractorProfileOut(
        company_name=profile.company_name,
        business_id=profile.business_id,
        description=profile.description,
        services=split_services(profile.services),
        service_area=profile.service_area,
        phone=profile.phone,
        website=profile.website,
        credit_balance=profile.credit_balance,
    )


@router.get("/me/contractor-profile", response_model=ContractorProfileOut)
def get_contractor_profile(
    user: User = Depends(require_contractor), db: Session = Depends(get_db)
) -> ContractorProfileOut:
    profile = db.scalar(select(ContractorProfile).where(ContractorProfile.user_id == user.id))
    if profile is None:
        raise AppError(404, "profile.missing")
    return _contractor_out(profile)


@router.put("/me/contractor-profile", response_model=ContractorProfileOut)
def upsert_contractor_profile(
    data: ContractorProfileIn,
    user: User = Depends(require_contractor),
    db: Session = Depends(get_db),
) -> ContractorProfileOut:
    business_id = data.business_id.strip() if data.business_id else None
    if business_id and not is_valid_business_id(business_id):
        raise AppError(422, "validation.invalid_business_id")
    for service in data.services:
        if service not in CATEGORIES:
            raise AppError(422, "validation.invalid_category", category=service)

    fields = data.model_dump(exclude={"services", "business_id"})
    fields["business_id"] = business_id or None
    fields["services"] = ",".join(dict.fromkeys(data.services))

    profile = db.scalar(select(ContractorProfile).where(ContractorProfile.user_id == user.id))
    if profile is None:
        profile = ContractorProfile(user_id=user.id, credit_balance=0, **fields)
        db.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
    db.commit()
    return _contractor_out(profile)


# --- public -----------------------------------------------------------------


@router.get("/contractors", response_model=list[PublicContractorOut])
def list_contractors(
    service: str | None = None,
    area: str | None = None,
    db: Session = Depends(get_db),
) -> list[PublicContractorOut]:
    query = (
        select(User, ContractorProfile)
        .join(ContractorProfile, ContractorProfile.user_id == User.id)
        .where(User.role == Role.contractor, User.status == UserStatus.active)
        .order_by(ContractorProfile.company_name)
    )
    if area:
        query = query.where(ContractorProfile.service_area.ilike(f"%{area}%"))
    rows = db.execute(query).all()
    result = [public_contractor_out(db, u, p) for u, p in rows]
    if service:
        result = [c for c in result if service in c.services]
    return result


@router.get("/contractors/{user_id}", response_model=PublicContractorOut)
def get_contractor(user_id: int, db: Session = Depends(get_db)) -> PublicContractorOut:
    row = db.execute(
        select(User, ContractorProfile)
        .join(ContractorProfile, ContractorProfile.user_id == User.id)
        .where(User.id == user_id, User.status == UserStatus.active)
    ).first()
    if row is None:
        raise AppError(404, "contractor.not_found")
    return public_contractor_out(db, *row)

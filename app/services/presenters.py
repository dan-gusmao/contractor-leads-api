"""Turn models into response schemas, enforcing who may see what."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import CATEGORIES
from ..models import (
    ContractorProfile,
    Project,
    ProjectImage,
    Review,
    ReviewStatus,
    Role,
    User,
)
from ..schemas import ContactOut, ImageOut, ProjectOut, PublicContractorOut, ReviewOut
from .credits import find_unlock


def category_label(category: str, lang: str) -> str:
    labels = CATEGORIES.get(category, {})
    return labels.get(lang) or labels.get("en") or category


def image_out(image: ProjectImage) -> ImageOut:
    return ImageOut(
        id=image.id,
        url=f"/projects/{image.project_id}/images/{image.id}",
        content_type=image.content_type,
    )


def can_see_contact(db: Session, project: Project, viewer: User | None) -> bool:
    """Contact details are hidden until a contractor unlocks them."""
    if viewer is None:
        return False
    if viewer.role is Role.admin or viewer.id == project.customer_id:
        return True
    if viewer.role is Role.contractor:
        return find_unlock(db, viewer.id, project.id) is not None
    return False


def contact_out(project: Project) -> ContactOut:
    return ContactOut(
        name=project.contact_name, email=project.contact_email, phone=project.contact_phone
    )


def project_out(
    db: Session, project: Project, viewer: User | None, lang: str, unlock_cost: int
) -> ProjectOut:
    visible = can_see_contact(db, project, viewer)
    is_owner_or_admin = viewer is not None and (
        viewer.role is Role.admin or viewer.id == project.customer_id
    )
    return ProjectOut(
        id=project.id,
        title=project.title,
        description=project.description,
        category=project.category,
        category_label=category_label(project.category, lang),
        location=project.location,
        budget_min=project.budget_min,
        budget_max=project.budget_max,
        status=project.status,
        created_at=project.created_at,
        images=[image_out(i) for i in project.images],
        unlock_cost=unlock_cost,
        contact_locked=not visible,
        contact=contact_out(project) if visible else None,
        rejection_reason=project.rejection_reason if is_owner_or_admin else None,
    )


def split_services(services: str | None) -> list[str]:
    return [s for s in (services or "").split(",") if s]


def public_contractor_out(db: Session, user: User, profile: ContractorProfile) -> PublicContractorOut:
    reviews = db.scalars(
        select(Review)
        .where(Review.contractor_id == user.id, Review.status == ReviewStatus.visible)
        .order_by(Review.created_at.desc())
    ).all()
    average = db.scalar(
        select(func.avg(Review.rating)).where(
            Review.contractor_id == user.id, Review.status == ReviewStatus.visible
        )
    )
    return PublicContractorOut(
        user_id=user.id,
        company_name=profile.company_name,
        business_id=profile.business_id,
        has_business_id=profile.business_id is not None,
        description=profile.description,
        services=split_services(profile.services),
        service_area=profile.service_area,
        website=profile.website,
        member_since=user.created_at,
        review_count=len(reviews),
        average_rating=round(float(average), 2) if average is not None else None,
        reviews=[ReviewOut.model_validate(r) for r in reviews],
    )

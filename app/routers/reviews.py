from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import get_db, require_customer
from ..i18n import AppError
from ..models import Project, Review, ReviewStatus, User
from ..schemas import ReviewIn, ReviewOut
from ..services.credits import find_unlock

router = APIRouter(tags=["reviews"])


@router.post("/reviews", response_model=ReviewOut, status_code=201)
def create_review(
    data: ReviewIn, user: User = Depends(require_customer), db: Session = Depends(get_db)
) -> Review:
    """A customer reviews a contractor who unlocked one of the customer's projects."""
    project = db.get(Project, data.project_id)
    if project is None or project.customer_id != user.id:
        raise AppError(403, "review.not_allowed")
    if find_unlock(db, data.contractor_id, project.id) is None:
        raise AppError(403, "review.not_allowed")

    review = Review(
        customer_id=user.id,
        contractor_id=data.contractor_id,
        project_id=project.id,
        rating=data.rating,
        comment=data.comment,
        status=ReviewStatus.visible,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "review.exists")
    return review


@router.get("/me/reviews", response_model=list[ReviewOut])
def my_reviews(user: User = Depends(require_customer), db: Session = Depends(get_db)) -> list[Review]:
    return list(
        db.scalars(select(Review).where(Review.customer_id == user.id).order_by(Review.id.desc()))
    )

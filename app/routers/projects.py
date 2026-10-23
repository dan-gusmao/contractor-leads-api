import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import CATEGORIES, Settings
from ..deps import get_db, get_optional_user, get_settings, require_contractor, require_customer
from ..i18n import AppError, resolve_language
from ..models import ContactUnlock, Project, ProjectImage, ProjectStatus, Role, User
from ..schemas import (
    ImageOut,
    ProjectIn,
    ProjectOut,
    ProjectPage,
    ProjectUpdateIn,
    UnlockedProjectOut,
    UnlockOut,
)
from ..services import credits
from ..services.presenters import contact_out, image_out, project_out

router = APIRouter(tags=["projects"])

EDITABLE = {ProjectStatus.draft, ProjectStatus.submitted, ProjectStatus.rejected, ProjectStatus.published}
SUBMITTABLE = {ProjectStatus.draft, ProjectStatus.rejected}

# Detect image type from file content, not from the client-supplied header.
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


def sniff_image(data: bytes) -> tuple[str, str] | None:
    for prefix, content_type, ext in _SIGNATURES:
        if data.startswith(prefix):
            return content_type, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def get_lang(request: Request) -> str:
    return resolve_language(request)


def _validate(category: str | None, budget_min: int | None, budget_max: int | None) -> None:
    if category is not None and category not in CATEGORIES:
        raise AppError(422, "validation.invalid_category", category=category)
    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        raise AppError(422, "validation.invalid_budget")


def _get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project.not_found")
    return project


def _own_project(db: Session, project_id: int, user: User) -> Project:
    project = _get_project(db, project_id)
    if project.customer_id != user.id:
        # Do not reveal that someone else's project exists.
        raise AppError(404, "project.not_found")
    return project


def _visible_project(db: Session, project_id: int, viewer: User | None) -> Project:
    project = _get_project(db, project_id)
    if project.status is ProjectStatus.published:
        return project
    if viewer is not None and (viewer.role is Role.admin or viewer.id == project.customer_id):
        return project
    raise AppError(404, "project.not_found")


@router.get("/categories")
def list_categories(lang: str = Depends(get_lang)) -> list[dict]:
    return [{"id": key, "label": labels.get(lang, labels["en"])} for key, labels in CATEGORIES.items()]


# --- customer ---------------------------------------------------------------


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    data: ProjectIn,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> ProjectOut:
    _validate(data.category, data.budget_min, data.budget_max)
    project = Project(customer_id=user.id, status=ProjectStatus.draft, **data.model_dump())
    db.add(project)
    db.commit()
    return project_out(db, project, user, lang, settings.unlock_cost)


@router.get("/me/projects", response_model=list[ProjectOut])
def my_projects(
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> list[ProjectOut]:
    projects = db.scalars(
        select(Project).where(Project.customer_id == user.id).order_by(Project.id.desc())
    ).all()
    return [project_out(db, p, user, lang, settings.unlock_cost) for p in projects]


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    data: ProjectUpdateIn,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> ProjectOut:
    project = _own_project(db, project_id, user)
    if project.status not in EDITABLE:
        raise AppError(409, "project.not_editable", status=project.status.value)

    changes = data.model_dump(exclude_unset=True)
    _validate(
        changes.get("category"),
        changes.get("budget_min", project.budget_min),
        changes.get("budget_max", project.budget_max),
    )
    for key, value in changes.items():
        setattr(project, key, value)

    # Edited public content must be moderated again before it is shown.
    if changes and project.status is ProjectStatus.published:
        project.status = ProjectStatus.submitted
        project.submitted_at = datetime.now(UTC)
    db.commit()
    return project_out(db, project, user, lang, settings.unlock_cost)


@router.post("/projects/{project_id}/submit", response_model=ProjectOut)
def submit_project(
    project_id: int,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> ProjectOut:
    project = _own_project(db, project_id, user)
    if project.status not in SUBMITTABLE:
        raise AppError(
            409, "project.invalid_transition", status=project.status.value, action="submitted"
        )
    project.status = ProjectStatus.submitted
    project.submitted_at = datetime.now(UTC)
    project.rejection_reason = None
    db.commit()
    return project_out(db, project, user, lang, settings.unlock_cost)


@router.post("/projects/{project_id}/images", response_model=ImageOut, status_code=201)
async def upload_image(
    project_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImageOut:
    project = _own_project(db, project_id, user)
    if len(project.images) >= settings.max_images_per_project:
        raise AppError(409, "image.too_many", limit=settings.max_images_per_project)

    data = await file.read(settings.max_image_bytes + 1)
    if len(data) > settings.max_image_bytes:
        raise AppError(413, "image.too_large", limit=settings.max_image_bytes)
    detected = sniff_image(data)
    if detected is None:
        raise AppError(415, "image.invalid_type")
    content_type, ext = detected

    directory = Path(settings.media_dir) / f"project_{project.id}"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (directory / filename).write_bytes(data)

    image = ProjectImage(project_id=project.id, filename=filename, content_type=content_type)
    db.add(image)
    db.commit()
    return image_out(image)


@router.delete("/projects/{project_id}/images/{image_id}", status_code=204)
def delete_image(
    project_id: int,
    image_id: int,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    project = _own_project(db, project_id, user)
    image = db.get(ProjectImage, image_id)
    if image is None or image.project_id != project.id:
        raise AppError(404, "image.not_found")
    path = Path(settings.media_dir) / f"project_{project.id}" / image.filename
    path.unlink(missing_ok=True)
    db.delete(image)
    db.commit()


@router.get("/projects/{project_id}/images/{image_id}")
def get_image(
    project_id: int,
    image_id: int,
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    project = _visible_project(db, project_id, viewer)
    image = db.get(ProjectImage, image_id)
    if image is None or image.project_id != project.id:
        raise AppError(404, "image.not_found")
    path = Path(settings.media_dir) / f"project_{project.id}" / image.filename
    if not path.is_file():
        raise AppError(404, "image.not_found")
    return FileResponse(path, media_type=image.content_type)


# --- public browsing & search -----------------------------------------------


@router.get("/projects", response_model=ProjectPage)
def list_projects(
    q: str | None = Query(default=None, max_length=200, description="Search title and description"),
    category: str | None = None,
    location: str | None = None,
    budget_min: int | None = Query(default=None, ge=0),
    budget_max: int | None = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> ProjectPage:
    query = select(Project).where(Project.status == ProjectStatus.published)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Project.title.ilike(pattern), Project.description.ilike(pattern)))
    if category:
        query = query.where(Project.category == category)
    if location:
        query = query.where(Project.location.ilike(f"%{location}%"))
    # Budget filters match projects whose budget range overlaps the requested one.
    if budget_min is not None:
        query = query.where(or_(Project.budget_max.is_(None), Project.budget_max >= budget_min))
    if budget_max is not None:
        query = query.where(or_(Project.budget_min.is_(None), Project.budget_min <= budget_max))

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    projects = db.scalars(
        query.order_by(Project.approved_at.desc(), Project.id.desc()).limit(limit).offset(offset)
    ).all()
    return ProjectPage(
        items=[project_out(db, p, viewer, lang, settings.unlock_cost) for p in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> ProjectOut:
    project = _visible_project(db, project_id, viewer)
    if viewer is None or viewer.id != project.customer_id:
        project.view_count += 1
        db.commit()
    return project_out(db, project, viewer, lang, settings.unlock_cost)


# --- contractor: unlocking --------------------------------------------------


@router.post("/projects/{project_id}/unlock", response_model=UnlockOut)
def unlock_project(
    project_id: int,
    user: User = Depends(require_contractor),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UnlockOut:
    project = _get_project(db, project_id)
    result = credits.unlock_contact(db, user, project, settings.unlock_cost)
    return UnlockOut(
        project_id=project.id,
        credits_spent=result.unlock.credits_spent,
        charged=result.charged,
        credit_balance=result.balance,
        contact=contact_out(project),
        unlocked_at=result.unlock.created_at,
    )


@router.get("/me/unlocks", response_model=list[UnlockedProjectOut])
def my_unlocks(
    user: User = Depends(require_contractor),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
) -> list[UnlockedProjectOut]:
    unlocks = db.scalars(
        select(ContactUnlock)
        .where(ContactUnlock.contractor_id == user.id)
        .order_by(ContactUnlock.id.desc())
    ).all()
    return [
        UnlockedProjectOut(
            project=project_out(db, u.project, user, lang, settings.unlock_cost),
            credits_spent=u.credits_spent,
            unlocked_at=u.created_at,
        )
        for u in unlocks
    ]

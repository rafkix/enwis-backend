import uuid

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import get_active_user, require_roles
from app.modules.auth.models import User
from app.modules.exams.apply_schemas import (
    ApplicantReview,
    ApplyLinkCreate,
    ApplySubmit,
)
from app.modules.exams.apply_service import ApplyService
from app.modules.exams.dependencies import get_db

router = APIRouter(prefix="/exams", tags=["Exam Apply"])


def _get_apply_service(db=Depends(get_db)) -> ApplyService:
    return ApplyService(db)


# ── Apply Links (Teacher/Admin) ───────────────────────────────────


@router.post("/{exam_id}/apply-links", status_code=201)
async def create_apply_link(
    exam_id: str,
    payload: ApplyLinkCreate,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    return await service.create_apply_link(
        uuid.UUID(exam_id), user.id,
        payload.max_uses, payload.expires_at,
    )


@router.get("/{exam_id}/apply-links")
async def list_apply_links(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    links = await service.list_apply_links(uuid.UUID(exam_id), user.id)
    return {"items": links}


@router.delete("/{exam_id}/apply-links/{link_id}", status_code=204)
async def deactivate_apply_link(
    exam_id: str,
    link_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    await service.deactivate_apply_link(uuid.UUID(link_id), user.id)


# ── Apply (Student) ───────────────────────────────────────────────


@router.post("/apply/{code}", status_code=201)
async def apply_by_link(
    code: str,
    payload: ApplySubmit | None = None,
    user: User = Depends(get_active_user),
    service: ApplyService = Depends(_get_apply_service),
):
    message = payload.message if payload else None
    return await service.apply_by_link(code, user.id, message)


@router.post("/{exam_id}/apply", status_code=201)
async def apply_direct(
    exam_id: str,
    payload: ApplySubmit | None = None,
    user: User = Depends(get_active_user),
    service: ApplyService = Depends(_get_apply_service),
):
    message = payload.message if payload else None
    return await service.apply_direct(uuid.UUID(exam_id), user.id, message)


@router.get("/{exam_id}/apply/status")
async def get_my_application(
    exam_id: str,
    user: User = Depends(get_active_user),
    service: ApplyService = Depends(_get_apply_service),
):
    result = await service.get_my_application(uuid.UUID(exam_id), user.id)
    if not result:
        return {"applied": False}
    return {"applied": True, **result}


# ── Review Applications (Teacher/Admin) ───────────────────────────


@router.get("/{exam_id}/applicants")
async def list_applicants(
    exam_id: str,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    return await service.list_applicants(
        uuid.UUID(exam_id), user.id, status, page, per_page,
    )


@router.post("/{exam_id}/applicants/{applicant_id}/review")
async def review_applicant(
    exam_id: str,
    applicant_id: str,
    payload: ApplicantReview,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    return await service.review_applicant(
        uuid.UUID(applicant_id), payload.status, user.id,
    )


@router.post("/{exam_id}/applicants/bulk-review")
async def bulk_review_applicants(
    exam_id: str,
    applicant_ids: list[uuid.UUID],
    status: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    return await service.bulk_review(applicant_ids, status, user.id)


@router.get("/{exam_id}/applicants/stats")
async def get_applicant_stats(
    exam_id: str,
    user: User = Depends(require_roles("TEACHER", "ADMIN")),
    service: ApplyService = Depends(_get_apply_service),
):
    return await service.get_stats(uuid.UUID(exam_id), user.id)

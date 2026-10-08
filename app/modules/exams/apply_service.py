import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.exams.apply_models import ApplicantStatus
from app.modules.exams.apply_repository import ApplicantRepository, ApplyLinkRepository
from app.modules.exams.exceptions import ExamNotFoundException
from app.modules.exams.models import Exam, ExamParticipant, ExamStatus
from app.modules.exams.repository import ExamRepository


class ApplyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.link_repo = ApplyLinkRepository(db)
        self.applicant_repo = ApplicantRepository(db)
        self.exam_repo = ExamRepository(db)

    async def _is_participant(self, exam_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(ExamParticipant).where(
                ExamParticipant.exam_id == exam_id,
                ExamParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None

    # ── Apply Links (Teacher/Admin) ───────────────────────────────────

    async def create_apply_link(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID,
        max_uses: int | None = None,
        expires_at: datetime | None = None,
    ) -> dict:
        exam = await self.exam_repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()

        link = await self.link_repo.create(exam_id, max_uses, expires_at)
        return {
            "id": link.id,
            "exam_id": link.exam_id,
            "code": link.code,
            "url": f"/apply/{link.code}",
            "max_uses": link.max_uses,
            "use_count": link.use_count,
            "expires_at": link.expires_at,
            "is_active": link.is_active,
            "created_at": link.created_at,
        }

    async def list_apply_links(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[dict]:
        exam = await self.exam_repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()

        links = await self.link_repo.list_by_exam(exam_id)
        return [
            {
                "id": link.id,
                "exam_id": link.exam_id,
                "code": link.code,
                "url": f"/apply/{link.code}",
                "max_uses": link.max_uses,
                "use_count": link.use_count,
                "expires_at": link.expires_at,
                "is_active": link.is_active,
                "created_at": link.created_at,
            }
            for link in links
        ]

    async def deactivate_apply_link(
        self, link_id: uuid.UUID, owner_id: uuid.UUID
    ) -> None:
        link = await self.link_repo.get_by_id(link_id)
        if not link:
            raise HTTPException(404, "Apply link not found")

        exam = await self.exam_repo.get_by_id_owner(link.exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()

        await self.link_repo.deactivate(link_id)

    async def delete_apply_link(
        self, link_id: uuid.UUID, owner_id: uuid.UUID
    ) -> None:
        link = await self.link_repo.get_by_id(link_id)
        if not link:
            raise HTTPException(404, "Apply link not found")

        exam = await self.exam_repo.get_by_id_owner(link.exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()

        await self.link_repo.delete(link_id)

    # ── Apply (Student) ───────────────────────────────────────────────

    async def apply_by_link(
        self, code: str, user_id: uuid.UUID, message: str | None = None
    ) -> dict:
        link = await self.link_repo.get_by_code(code)
        if not link:
            raise HTTPException(404, "Apply link not found or inactive")

        if link.expires_at and link.expires_at < datetime.now(UTC):
            raise HTTPException(400, "Apply link has expired")

        if link.max_uses and link.use_count >= link.max_uses:
            raise HTTPException(400, "Apply link has reached maximum uses")

        existing = await self.applicant_repo.get_by_exam_user(link.exam_id, user_id)
        if existing:
            raise HTTPException(400, "You have already applied to this exam")

        if await self._is_participant(link.exam_id, user_id):
            raise HTTPException(400, "You are already a participant of this exam")

        applicant = await self.applicant_repo.create(
            link.exam_id, user_id, link.id, message
        )
        await self.link_repo.increment_use_count(link.id)
        await self.db.commit()

        return {
            "id": applicant.id,
            "exam_id": applicant.exam_id,
            "status": applicant.status.value,
            "created_at": applicant.created_at,
        }

    async def apply_direct(
        self, exam_id: uuid.UUID, user_id: uuid.UUID, message: str | None = None
    ) -> dict:
        exam_result = await self.db.execute(
            select(Exam).where(Exam.id == exam_id)
        )
        exam = exam_result.scalar_one_or_none()
        if not exam:
            raise ExamNotFoundException()

        if exam.status != ExamStatus.ACTIVE:
            raise HTTPException(400, "Exam is not active")

        existing = await self.applicant_repo.get_by_exam_user(exam_id, user_id)
        if existing:
            raise HTTPException(400, "You have already applied to this exam")

        if await self._is_participant(exam_id, user_id):
            raise HTTPException(400, "You are already a participant of this exam")

        applicant = await self.applicant_repo.create(exam_id, user_id, None, message)
        await self.db.commit()

        return {
            "id": applicant.id,
            "exam_id": applicant.exam_id,
            "status": applicant.status.value,
            "created_at": applicant.created_at,
        }

    async def get_my_application(
        self, exam_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict | None:
        applicant = await self.applicant_repo.get_by_exam_user(exam_id, user_id)
        if not applicant:
            return None
        return {
            "id": applicant.id,
            "exam_id": applicant.exam_id,
            "user_id": applicant.user_id,
            "status": applicant.status.value,
            "message": applicant.message,
            "created_at": applicant.created_at,
        }

    # ── Review Applications (Teacher/Admin) ───────────────────────────

    async def list_applicants(
        self, exam_id: uuid.UUID, owner_id: uuid.UUID,
        status_filter: str | None = None,
        page: int = 1, per_page: int = 20,
    ) -> dict:
        exam = await self.exam_repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()

        result = await self.applicant_repo.list_by_exam(
            exam_id, status_filter, page, per_page
        )

        items = []
        for a in result["items"]:
            items.append({
                "id": a.id,
                "exam_id": a.exam_id,
                "user_id": a.user_id,
                "user_name": a.user.full_name if a.user else None,
                "user_email": a.user.email if a.user else None,
                "status": a.status.value,
                "message": a.message,
                "reviewed_by_id": a.reviewed_by_id,
                "reviewed_at": a.reviewed_at,
                "created_at": a.created_at,
            })

        return {
            "items": items,
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
        }

    async def review_applicant(
        self, applicant_id: uuid.UUID, status: str, reviewer_id: uuid.UUID
    ) -> dict:
        applicant = await self.applicant_repo.get_by_id(applicant_id)
        if not applicant:
            raise HTTPException(404, "Applicant not found")

        exam = await self.exam_repo.get_by_id_owner(applicant.exam_id, reviewer_id)
        if not exam:
            raise ExamNotFoundException()

        if applicant.status != ApplicantStatus.PENDING:
            raise HTTPException(400, "Applicant has already been reviewed")

        updated = await self.applicant_repo.update_status(
            applicant_id, status, reviewer_id
        )

        is_approved = status == "approved"
        already_participant = await self._is_participant(
            applicant.exam_id, applicant.user_id
        )
        if is_approved and not already_participant:
            participant = ExamParticipant(
                exam_id=applicant.exam_id,
                user_id=applicant.user_id,
            )
            self.db.add(participant)
            await self.db.flush()

        await self.db.commit()

        from app.modules.notifications.events import (
            notify_registration_approved,
            notify_registration_rejected,
        )

        if is_approved:
            await notify_registration_approved(
                self.db, user_id=applicant.user_id, test_title=exam.title
            )
        else:
            await notify_registration_rejected(
                self.db, user_id=applicant.user_id, test_title=exam.title
            )

        return {
            "id": updated.id,
            "exam_id": updated.exam_id,
            "user_id": updated.user_id,
            "status": updated.status.value,
            "reviewed_at": updated.reviewed_at,
        }

    async def bulk_review(
        self, applicant_ids: list[uuid.UUID], status: str, reviewer_id: uuid.UUID
    ) -> dict:
        approved = 0
        rejected = 0

        for aid in applicant_ids:
            try:
                result = await self.review_applicant(aid, status, reviewer_id)
                if result["status"] == "approved":
                    approved += 1
                else:
                    rejected += 1
            except HTTPException:
                continue

        return {"approved": approved, "rejected": rejected}

    async def get_stats(self, exam_id: uuid.UUID, owner_id: uuid.UUID) -> dict:
        exam = await self.exam_repo.get_by_id_owner(exam_id, owner_id)
        if not exam:
            raise ExamNotFoundException()

        total = await self.applicant_repo.count_by_exam(exam_id)
        pending = await self.applicant_repo.count_by_exam_status(exam_id, "pending")
        approved = await self.applicant_repo.count_by_exam_status(exam_id, "approved")
        rejected = await self.applicant_repo.count_by_exam_status(exam_id, "rejected")

        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
        }

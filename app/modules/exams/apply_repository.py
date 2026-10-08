import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.exams.apply_models import (
    ApplicantStatus,
    ExamApplicant,
    ExamApplyLink,
)


class ApplyLinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, exam_id: uuid.UUID, max_uses: int | None = None,
        expires_at: datetime | None = None,
    ) -> ExamApplyLink:
        link = ExamApplyLink(
            exam_id=exam_id,
            max_uses=max_uses,
            expires_at=expires_at,
        )
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def get_by_code(self, code: str) -> ExamApplyLink | None:
        result = await self.db.execute(
            select(ExamApplyLink)
            .options(selectinload(ExamApplyLink.exam))
            .where(ExamApplyLink.code == code, ExamApplyLink.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, link_id: uuid.UUID) -> ExamApplyLink | None:
        result = await self.db.execute(
            select(ExamApplyLink).where(ExamApplyLink.id == link_id)
        )
        return result.scalar_one_or_none()

    async def list_by_exam(self, exam_id: uuid.UUID) -> list[ExamApplyLink]:
        result = await self.db.execute(
            select(ExamApplyLink)
            .where(ExamApplyLink.exam_id == exam_id)
            .order_by(ExamApplyLink.created_at.desc())
        )
        return list(result.scalars().all())

    async def increment_use_count(self, link_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ExamApplyLink).where(ExamApplyLink.id == link_id)
        )
        link = result.scalar_one_or_none()
        if link:
            link.use_count += 1
            if link.max_uses and link.use_count >= link.max_uses:
                link.is_active = False
            await self.db.flush()

    async def deactivate(self, link_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ExamApplyLink).where(ExamApplyLink.id == link_id)
        )
        link = result.scalar_one_or_none()
        if link:
            link.is_active = False
            await self.db.flush()

    async def delete(self, link_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ExamApplyLink).where(ExamApplyLink.id == link_id)
        )
        link = result.scalar_one_or_none()
        if link:
            await self.db.delete(link)
            await self.db.flush()


class ApplicantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, exam_id: uuid.UUID, user_id: uuid.UUID,
        apply_link_id: uuid.UUID | None = None,
        message: str | None = None,
    ) -> ExamApplicant:
        applicant = ExamApplicant(
            exam_id=exam_id,
            user_id=user_id,
            apply_link_id=apply_link_id,
            message=message,
        )
        self.db.add(applicant)
        await self.db.flush()
        await self.db.refresh(applicant)
        return applicant

    async def get_by_exam_user(
        self, exam_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExamApplicant | None:
        result = await self.db.execute(
            select(ExamApplicant).where(
                ExamApplicant.exam_id == exam_id,
                ExamApplicant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, applicant_id: uuid.UUID) -> ExamApplicant | None:
        result = await self.db.execute(
            select(ExamApplicant)
            .options(
                selectinload(ExamApplicant.user),
                selectinload(ExamApplicant.reviewed_by),
            )
            .where(ExamApplicant.id == applicant_id)
        )
        return result.scalar_one_or_none()

    async def list_by_exam(
        self, exam_id: uuid.UUID,
        status_filter: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        q = select(ExamApplicant).options(
            selectinload(ExamApplicant.user),
            selectinload(ExamApplicant.reviewed_by),
        ).where(ExamApplicant.exam_id == exam_id)

        count_q = select(func.count(ExamApplicant.id)).where(
            ExamApplicant.exam_id == exam_id
        )

        if status_filter:
            q = q.where(ExamApplicant.status == status_filter)
            count_q = count_q.where(ExamApplicant.status == status_filter)

        total = (await self.db.execute(count_q)).scalar_one()

        result = await self.db.execute(
            q.order_by(ExamApplicant.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        applicants = list(result.scalars().all())

        return {
            "items": applicants,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    async def update_status(
        self, applicant_id: uuid.UUID, status: str, reviewer_id: uuid.UUID
    ) -> ExamApplicant | None:
        result = await self.db.execute(
            select(ExamApplicant).where(ExamApplicant.id == applicant_id)
        )
        applicant = result.scalar_one_or_none()
        if not applicant:
            return None
        applicant.status = ApplicantStatus(status)
        applicant.reviewed_by_id = reviewer_id
        applicant.reviewed_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(applicant)
        return applicant

    async def count_by_exam(self, exam_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(ExamApplicant.id)).where(
                ExamApplicant.exam_id == exam_id
            )
        )
        return result.scalar_one() or 0

    async def count_by_exam_status(self, exam_id: uuid.UUID, status: str) -> int:
        result = await self.db.execute(
            select(func.count(ExamApplicant.id)).where(
                ExamApplicant.exam_id == exam_id,
                ExamApplicant.status == status,
            )
        )
        return result.scalar_one() or 0

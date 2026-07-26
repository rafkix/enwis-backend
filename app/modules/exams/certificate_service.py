import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.exams.attempt_exceptions import AttemptNotFound, NotAttemptOwner
from app.modules.exams.certificate_exceptions import (
    CertificateNotEligible,
    CertificateNotFound,
    CertificatesDisabled,
    NotCertificateOwner,
)
from app.modules.exams.certificate_repository import CertificateRepository
from app.modules.exams.models import Certificate, ExamAttempt, Result


def _now() -> datetime:
    return datetime.now(UTC)


def _generate_serial() -> str:
    # e.g. ENWIS-8F3K2Q9R — short, uppercase, easy to read/type/verify.
    return f"ENWIS-{secrets.token_hex(4).upper()}"


class CertificateService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CertificateRepository(db)

    async def _generate_unique_serial(self) -> str:
        for _ in range(10):
            serial = _generate_serial()
            if not await self.repo.serial_exists(serial):
                return serial
        # Astronomically unlikely, but fall back to a longer token.
        return f"ENWIS-{secrets.token_hex(6).upper()}"

    async def issue_for_attempt(
        self, attempt: ExamAttempt, *, force: bool = False
    ) -> Certificate | None:
        """Issue a certificate for a completed, passed attempt, if the exam's
        test has certificates enabled. Idempotent: returns the existing
        certificate if one was already issued for this attempt.

        Returns ``None`` (rather than raising) when the attempt exists but
        certificates simply aren't applicable — this is called automatically
        from the submit/grade flow and shouldn't ever block a student's
        result from being returned.
        """
        existing = await self.repo.get_by_attempt(attempt.id)
        if existing:
            return existing

        if not attempt.is_completed:
            return None

        exam = attempt.exam
        test = exam.test if exam else None
        certificate_enabled = bool(
            test.settings.certificate_enabled if getattr(test, "settings", None) else False
        )
        if not certificate_enabled and not force:
            return None

        result_row = await self.db.execute(
            select(Result).where(Result.attempt_id == attempt.id)
        )
        result = result_row.scalar_one_or_none()
        if not result or not result.passed:
            return None

        user_result = await self.db.execute(select(User).where(User.id == attempt.user_id))
        user = user_result.scalar_one_or_none()
        recipient_name = (user.full_name if user and user.full_name else None) or (
            user.username if user else "Participant"
        )

        serial_number = await self._generate_unique_serial()

        certificate = Certificate(
            attempt_id=attempt.id,
            exam_id=exam.id,
            user_id=attempt.user_id,
            serial_number=serial_number,
            recipient_name=recipient_name,
            exam_title=exam.title,
            score_percentage=result.percentage,
            grade=result.grade,
            issued_at=_now(),
        )
        self.repo.add(certificate)
        await self.db.flush()

        from app.modules.notifications.events import notify_certificate_ready

        await notify_certificate_ready(
            self.db,
            user_id=attempt.user_id,
            exam_title=exam.title,
            serial_number=serial_number,
        )

        return certificate

    async def issue_manually(self, attempt_id: uuid.UUID, requester_id: uuid.UUID) -> Certificate:
        """Explicit issuance endpoint for a participant who wants to fetch
        (or lazily trigger) their certificate after passing.
        """
        result = await self.db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.id == attempt_id)
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise AttemptNotFound()
        if attempt.user_id != requester_id:
            raise NotAttemptOwner()

        # Reload with relations needed for issuance.
        from app.modules.exams.attempt_repository import AttemptRepository

        attempt = await AttemptRepository(self.db).get_attempt_with_relations(attempt_id)
        if not attempt:
            raise AttemptNotFound()

        exam = attempt.exam
        test = exam.test if exam else None
        test_settings_enabled = bool(
            test.settings.certificate_enabled if getattr(test, "settings", None) else False
        )
        if not test_settings_enabled:
            raise CertificatesDisabled()

        result_row = await self.db.execute(
            select(Result).where(Result.attempt_id == attempt.id)
        )
        result_record = result_row.scalar_one_or_none()
        if not attempt.is_completed or not result_record:
            raise CertificateNotEligible("This attempt has not been completed yet")
        if not result_record.passed:
            raise CertificateNotEligible("A passing score is required to receive a certificate")

        certificate = await self.issue_for_attempt(attempt, force=True)
        if not certificate:
            raise CertificateNotEligible()
        return certificate

    async def get_by_id_for_user(
        self, certificate_id: uuid.UUID, user_id: uuid.UUID
    ) -> Certificate:
        certificate = await self.repo.get_by_id(certificate_id)
        if not certificate:
            raise CertificateNotFound()
        if certificate.user_id != user_id:
            raise NotCertificateOwner()
        return certificate

    async def verify_by_serial(self, serial_number: str) -> Certificate:
        """Public verification lookup — no ownership check, used for e.g.
        an employer scanning a QR code / entering the serial on a public page.
        """
        certificate = await self.repo.get_by_serial(serial_number)
        if not certificate or certificate.revoked_at is not None:
            raise CertificateNotFound()
        return certificate

    async def list_my_certificates(self, user_id: uuid.UUID) -> list[Certificate]:
        return await self.repo.list_for_user(user_id)

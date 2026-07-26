"""Notification helpers that integrate with the exam / test lifecycle.

These functions are called from exam and test services to create
in-app notifications when key events occur.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)


async def notify_exam_published(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    exam_title: str,
) -> None:
    """Create a notification when an exam is published."""
    service = NotificationService(db)
    await service.create(
        user_id=owner_id,
        type=NotificationType.EXAM,
        title="Exam Published",
        message=f'Exam "{exam_title}" has been published and is now active.',
    )


async def notify_exam_completed(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    exam_title: str,
    score: float | None = None,
) -> None:
    """Create a notification when a student completes an exam."""
    service = NotificationService(db)
    msg = f'You completed exam "{exam_title}".'
    if score is not None:
        msg += f" Score: {score}"
    await service.create(
        user_id=student_id,
        type=NotificationType.ATTEMPT,
        title="Exam Completed",
        message=msg,
    )


async def notify_registration_approved(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    test_title: str,
) -> None:
    """Notify a student that their exam registration was approved."""
    service = NotificationService(db)
    await service.create(
        user_id=user_id,
        type=NotificationType.SYSTEM,
        title="Registration Approved",
        message=(
            f"Your registration for '{test_title}' has been approved. "
            "You can now take the exam."
        ),
    )


async def notify_registration_rejected(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    test_title: str,
) -> None:
    """Notify a student that their exam registration was rejected."""
    service = NotificationService(db)
    await service.create(
        user_id=user_id,
        type=NotificationType.SYSTEM,
        title="Registration Rejected",
        message=f"Your registration for '{test_title}' has been rejected.",
    )


async def notify_result_ready(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    test_title: str,
    score: float | None = None,
) -> None:
    """Notify a student that their test result is ready."""
    service = NotificationService(db)
    msg = f"Your result for '{test_title}' is ready."
    if score is not None:
        msg += f" Score: {score:.1f}"
    await service.create(
        user_id=user_id,
        type=NotificationType.RESULT,
        title="Result Ready",
        message=msg,
    )


async def notify_certificate_ready(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    exam_title: str,
    serial_number: str,
) -> None:
    """Notify a student that their certificate has been issued."""
    service = NotificationService(db)
    await service.create(
        user_id=user_id,
        type=NotificationType.RESULT,
        title="Certificate Ready",
        message=(
            f"Your certificate for '{exam_title}' is ready "
            f"(serial: {serial_number})."
        ),
    )

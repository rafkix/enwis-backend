from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    Notification,
    NotificationPriority,
    NotificationType,
)
from app.modules.notifications.schemas import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
)


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: UUID,
        type: NotificationType,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            type=type,
            priority=priority,
            title=title,
            message=message,
            data=data or {},
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def create_system(
        self,
        user_id: UUID,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        return await self.create(
            user_id=user_id,
            type=NotificationType.SYSTEM,
            title=title,
            message=message,
            priority=priority,
            data=data,
        )

    async def create_exam_created(
        self,
        user_id: UUID,
        exam_title: str,
        exam_id: UUID,
    ) -> Notification:
        return await self.create(
            user_id=user_id,
            type=NotificationType.EXAM,
            title="New Exam Created",
            message=f'Exam "{exam_title}" has been created.',
            priority=NotificationPriority.NORMAL,
            data={"exam_id": str(exam_id), "action": "created"},
        )

    async def create_exam_started(
        self,
        user_id: UUID,
        exam_title: str,
        exam_id: UUID,
    ) -> Notification:
        return await self.create(
            user_id=user_id,
            type=NotificationType.EXAM,
            title="Exam Started",
            message=f'Exam "{exam_title}" has started.',
            priority=NotificationPriority.HIGH,
            data={"exam_id": str(exam_id), "action": "started"},
        )

    async def create_exam_completed(
        self,
        user_id: UUID,
        exam_title: str,
        exam_id: UUID,
        score: int | None = None,
    ) -> Notification:
        msg = f'Exam "{exam_title}" completed.'
        if score is not None:
            msg += f" Score: {score}%"
        return await self.create(
            user_id=user_id,
            type=NotificationType.ATTEMPT,
            title="Exam Completed",
            message=msg,
            priority=NotificationPriority.NORMAL,
            data={"exam_id": str(exam_id), "score": score},
        )

    async def create_grade_received(
        self,
        user_id: UUID,
        exam_title: str,
        score: int,
        exam_id: UUID,
    ) -> Notification:
        return await self.create(
            user_id=user_id,
            type=NotificationType.RESULT,
            title="Grade Received",
            message=f'You scored {score}% on "{exam_title}".',
            priority=NotificationPriority.NORMAL,
            data={"exam_id": str(exam_id), "score": score},
        )

    async def create_reminder(
        self,
        user_id: UUID,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        return await self.create(
            user_id=user_id,
            type=NotificationType.REMINDER,
            title=title,
            message=message,
            priority=NotificationPriority.HIGH,
            data=data,
        )

    async def create_promotion(
        self,
        user_id: UUID,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        return await self.create(
            user_id=user_id,
            type=NotificationType.PROMOTION,
            title=title,
            message=message,
            priority=NotificationPriority.LOW,
            data=data,
        )

    async def get_list(
        self,
        user_id: UUID,
        page: int = 1,
        per_page: int = 20,
        unread_only: bool = False,
    ) -> NotificationListResponse:
        query = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            query = query.where(Notification.is_read.is_(False))

        query = query.order_by(Notification.created_at.desc())

        total_stmt = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(total_stmt)).scalar() or 0

        offset = (page - 1) * per_page
        rows = (await self.db.execute(query.offset(offset).limit(per_page))).scalars().all()

        unread_count_stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        unread_count = (await self.db.execute(unread_count_stmt)).scalar() or 0

        return NotificationListResponse(
            items=[NotificationResponse.model_validate(n) for n in rows],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if total > 0 else 0,
            unread_count=unread_count,
        )

    async def get_unread_count(self, user_id: UUID) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        return (await self.db.execute(stmt)).scalar() or 0

    async def mark_as_read(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        notification = result.scalar_one_or_none()

        if notification and not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(UTC)
            await self.db.commit()
            await self.db.refresh(notification)

        return notification

    async def mark_all_read(self, user_id: UUID) -> MarkAllReadResponse:
        from sqlalchemy import update as sql_update

        now = datetime.now(UTC)
        stmt = (
            sql_update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=now)
        )
        result = await self.db.execute(stmt)
        count = result.rowcount

        if count > 0:
            await self.db.commit()

        return MarkAllReadResponse(updated_count=count)

    async def delete(self, notification_id: UUID, user_id: UUID) -> bool:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        notification = result.scalar_one_or_none()

        if notification:
            await self.db.delete(notification)
            await self.db.commit()
            return True
        return False

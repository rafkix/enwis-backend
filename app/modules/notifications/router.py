from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications.schemas import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.modules.notifications.service import NotificationService

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
    dependencies=[Depends(get_current_user)],
)


def get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="List notifications",
    responses={
        200: {"description": "Notifications returned successfully."},
        401: {"description": "Not authenticated — Bearer token missing or expired."},
    },
)
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.get_list(user.id, page, per_page, unread_only)


@router.get(
    "/unread-count",
    summary="Get unread notification count",
    responses={
        200: {"description": "Unread count returned successfully."},
        401: {"description": "Not authenticated — Bearer token missing or expired."},
    },
)
async def get_unread_count(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    count = await service.get_unread_count(user.id)
    return {"count": count}


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark notification as read",
    responses={
        200: {"description": "Notification marked as read."},
        401: {"description": "Not authenticated."},
        404: {"description": "Notification not found."},
    },
)
async def mark_as_read(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    notification = await service.mark_as_read(notification_id, user.id)
    if not notification:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Notification not found")
    return NotificationResponse.model_validate(notification)


@router.post(
    "/read-all",
    response_model=MarkAllReadResponse,
    summary="Mark all notifications as read",
    responses={
        200: {"description": "All notifications marked as read."},
        401: {"description": "Not authenticated."},
    },
)
async def mark_all_read(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.mark_all_read(user.id)


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete notification",
    responses={
        204: {"description": "Notification deleted."},
        401: {"description": "Not authenticated."},
        404: {"description": "Notification not found."},
    },
)
async def delete_notification(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    deleted = await service.delete(notification_id, user.id)
    if not deleted:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Notification not found")

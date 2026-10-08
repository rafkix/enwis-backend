import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.subscriptions.schemas import (
    PlanListResponse,
    PlanResponse,
    SubscribeRequest,
)
from app.modules.subscriptions.service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

# NOTE: Plan CRUD (create/update/delete/seed) and payment moderation
# (approve/reject) require ADMIN privileges and live in the `admin`
# module (/admin/plans, /admin/payments) — they are intentionally not
# exposed here. This router is the read-only, user-facing surface plus
# the free-plan direct-subscribe shortcut. Paid plans go through
# /billing/payments (see billing_router.py).


def get_service(db: AsyncSession = Depends(get_db)) -> SubscriptionService:
    return SubscriptionService(db)


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    active_only: bool = Query(False),
    service: SubscriptionService = Depends(get_service),
):
    plans = await service.list_plans(active_only)
    return {"items": plans, "total": len(plans)}


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    service: SubscriptionService = Depends(get_service),
):
    return await service.get_plan(uuid.UUID(plan_id))


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: SubscribeRequest,
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    """Direct activation — only works for free (price == 0) plans. Paid
    plans must go through POST /billing/payments instead."""
    return await service.subscribe(user.id, payload.plan_id, payload.payment_id)


@router.post("/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: str,
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    return await service.cancel_subscription(user.id, uuid.UUID(subscription_id))


@router.get("/me")
async def get_my_subscription(
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    result = await service.get_user_subscription(user.id)
    if not result:
        return {"active": False}
    return {"active": True, **result}


@router.get("/me/history")
async def get_my_subscription_history(
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    history = await service.get_user_subscription_history(user.id)
    return {"items": history}

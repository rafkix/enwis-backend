import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.subscriptions.schemas import (
    PlanCreate,
    PlanListResponse,
    PlanResponse,
    PlanUpdate,
    SubscribeRequest,
)
from app.modules.subscriptions.service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


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


@router.post("/plans", response_model=PlanResponse, status_code=201)
async def create_plan(
    payload: PlanCreate,
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    return await service.create_plan(payload.model_dump())


@router.put("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: str,
    payload: PlanUpdate,
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    return await service.update_plan(
        uuid.UUID(plan_id),
        {k: v for k, v in payload.model_dump().items() if v is not None},
    )


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(
    plan_id: str,
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    await service.delete_plan(uuid.UUID(plan_id))


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: SubscribeRequest,
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
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


@router.post("/seed", status_code=200)
async def seed_plans(
    user: User = Depends(get_active_user),
    service: SubscriptionService = Depends(get_service),
):
    await service.seed_default_plans()
    return {"success": True, "message": "Default plans seeded"}

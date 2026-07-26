from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.dashboard.schemas import DashboardStatsResponse, PublicStatsResponse
from app.modules.dashboard.service import DashboardService, PublicStatsService

# ── Authenticated dashboard router ────────────────────────────────

dashboard_router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)


@dashboard_router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Get user dashboard statistics",
    description=(
        "Returns the authenticated user's personal statistics: "
        "XP/level/streak, test & question counts, exam attempts, "
        "scores, pass rates, certificates, and unread notifications."
    ),
)
async def get_dashboard_stats(
    user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardStatsResponse:
    service = DashboardService(db)
    return await service.get_user_stats(user)


# ── Public stats router ──────────────────────────────────────────

public_router = APIRouter(
    prefix="/public",
    tags=["Public"],
)


@public_router.get(
    "/stats",
    response_model=PublicStatsResponse,
    summary="Get public platform statistics",
    description=(
        "Returns aggregate platform statistics: total users, exams, "
        "questions, attempts, and certificates. No authentication required."
    ),
)
async def get_public_stats(
    db: AsyncSession = Depends(get_db),
) -> PublicStatsResponse:
    service = PublicStatsService(db)
    return await service.get_platform_stats()

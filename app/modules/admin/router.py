import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.auth.models import User

# A single checker instance so FastAPI's per-request dependency cache
# (default: on) actually kicks in — using it both as the router-level
# `dependencies=[...]` gate and per-endpoint `Depends(require_admin)`
# for the acting User means the role check only runs once per request
# instead of twice.
require_admin = require_roles("ADMIN")
from app.modules.admin.schemas import (
    AdminApprovePaymentRequest,
    AdminAuditLogListResponse,
    AdminDashboardResponse,
    AdminRejectPaymentRequest,
    AdminUserListItem,
    AdminUserListResponse,
    UpdateUserAIQuotaRequest,
    UpdateUserRolesRequest,
    UpdateUserStatusRequest,
)
from app.modules.admin.service import AdminService
from app.modules.subscriptions.schemas import (
    PaymentCardCreate,
    PaymentCardListResponse,
    PaymentCardResponse,
    PaymentCardUpdate,
    PaymentListResponse,
    PaymentResponse,
    PlanCreate,
    PlanListResponse,
    PlanResponse,
    PlanUpdate,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


def get_service(db: AsyncSession = Depends(get_db)) -> AdminService:
    return AdminService(db)


# ── Dashboard ────────────────────────────────────────────────────


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(service: AdminService = Depends(get_service)):
    return await service.get_dashboard()


# ── User management ─────────────────────────────────────────────


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status: str | None = Query(None),
    role: str | None = Query(None),
    service: AdminService = Depends(get_service),
):
    rows, total = await service.list_users(page, per_page, search, status, role)
    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.get("/users/{user_id}", response_model=AdminUserListItem)
async def get_user(user_id: uuid.UUID, service: AdminService = Depends(get_service)):
    return await service.get_user(user_id)


@router.patch("/users/{user_id}/status", response_model=AdminUserListItem)
async def update_user_status(
    user_id: uuid.UUID,
    payload: UpdateUserStatusRequest,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    return await service.update_user_status(admin, user_id, payload.status, payload.reason)


@router.patch("/users/{user_id}/roles", response_model=AdminUserListItem)
async def update_user_roles(
    user_id: uuid.UUID,
    payload: UpdateUserRolesRequest,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    return await service.update_user_roles(admin, user_id, payload.roles)


@router.patch("/users/{user_id}/ai-quota", response_model=AdminUserListItem)
async def update_user_ai_quota(
    user_id: uuid.UUID,
    payload: UpdateUserAIQuotaRequest,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    """Override a user's monthly AI question quota (null clears it, -1 = unlimited)."""
    return await service.update_user_ai_quota(
        admin, user_id, payload.quota_override, payload.reason
    )


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    await service.delete_user(admin, user_id)


# ── Payment moderation ──────────────────────────────────────────


@router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    status: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: AdminService = Depends(get_service),
):
    rows, total = await service.list_payments(status, user_id, page, per_page)
    serialize = service.billing_service.serialize_payment
    return {
        "items": [serialize(p) for p in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: uuid.UUID, service: AdminService = Depends(get_service)):
    payment = await service.get_payment(payment_id)
    return service.billing_service.serialize_payment(payment)


@router.get("/payments/{payment_id}/receipt")
async def get_payment_receipt(payment_id: uuid.UUID, service: AdminService = Depends(get_service)):
    path = await service.get_receipt_file_path(payment_id)
    return FileResponse(path)


@router.post("/payments/{payment_id}/approve", response_model=PaymentResponse)
async def approve_payment(
    payment_id: uuid.UUID,
    payload: AdminApprovePaymentRequest,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    payment = await service.approve_payment(admin, payment_id, payload.note)
    return service.billing_service.serialize_payment(payment)


@router.post("/payments/{payment_id}/reject", response_model=PaymentResponse)
async def reject_payment(
    payment_id: uuid.UUID,
    payload: AdminRejectPaymentRequest,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    payment = await service.reject_payment(admin, payment_id, payload.reason)
    return service.billing_service.serialize_payment(payment)


# ── Plan management ─────────────────────────────────────────────


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(service: AdminService = Depends(get_service)):
    plans = await service.sub_service.list_plans(active_only=False)
    return {"items": plans, "total": len(plans)}


@router.post("/plans", response_model=PlanResponse, status_code=201)
async def create_plan(
    payload: PlanCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    return await service.create_plan(admin, payload.model_dump())


@router.put("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    return await service.update_plan(
        admin, plan_id, {k: v for k, v in payload.model_dump().items() if v is not None}
    )


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(
    plan_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    await service.delete_plan(admin, plan_id)


@router.post("/plans/seed", status_code=200)
async def seed_plans(service: AdminService = Depends(get_service)):
    await service.seed_default_plans()
    return {"success": True, "message": "Default plans seeded"}


# ── Payment card management ─────────────────────────────────────


@router.get("/cards", response_model=PaymentCardListResponse)
async def list_cards(service: AdminService = Depends(get_service)):
    cards = await service.list_cards()
    return {"items": cards, "total": len(cards)}


@router.post("/cards", response_model=PaymentCardResponse, status_code=201)
async def create_card(
    payload: PaymentCardCreate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    return await service.create_card(admin, payload.model_dump())


@router.put("/cards/{card_id}", response_model=PaymentCardResponse)
async def update_card(
    card_id: uuid.UUID,
    payload: PaymentCardUpdate,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    return await service.update_card(
        admin, card_id, {k: v for k, v in payload.model_dump().items() if v is not None}
    )


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(
    card_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_service),
):
    await service.delete_card(admin, card_id)


# ── Audit logs ───────────────────────────────────────────────────


@router.get("/logs", response_model=AdminAuditLogListResponse)
async def list_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    service: AdminService = Depends(get_service),
):
    rows, total = await service.list_audit_logs(page, per_page, action, target_type)
    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }

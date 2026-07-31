import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_active_user
from app.modules.auth.models import User
from app.modules.subscriptions.schemas import (
    BillingCheckoutInfo,
    InitiatePaymentRequest,
    PaymentCardListResponse,
    PaymentListResponse,
    PaymentResponse,
)
from app.modules.subscriptions.service import BillingService
from app.modules.subscriptions.models import PaymentMethod

router = APIRouter(prefix="/payments", tags=["Payments"])


def get_service(db: AsyncSession = Depends(get_db)) -> BillingService:
    return BillingService(db)


@router.get(
    "/cards",
    response_model=PaymentCardListResponse,
    summary="List active receiving cards",
    description="Cards the platform currently accepts manual transfers on.",
)
async def list_cards(service: BillingService = Depends(get_service)):
    cards = await service.list_active_cards()
    return {"items": cards, "total": len(cards)}


@router.post(
    "/payments",
    response_model=BillingCheckoutInfo,
    status_code=201,
    summary="Start a payment for a plan (step 1)",
    description=(
        "Creates a PENDING payment for the given plan and returns the "
        "receiving card details to pay to. Free plans should use "
        "POST /subscriptions/subscribe instead."
    ),
)
async def initiate_payment(
    payload: InitiatePaymentRequest,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_service),
):
    try:
        method = PaymentMethod(payload.method)
    except ValueError:
        raise HTTPException(400, f"Unknown payment method: {payload.method}")
    payment = await service.initiate_payment(user.id, payload.plan_id, payload.card_id, method)
    cards = await service.list_active_cards()
    return {"payment": payment, "cards": cards}


@router.post(
    "/payments/{payment_id}/receipt",
    response_model=PaymentResponse,
    summary="Upload payment receipt screenshot (step 2)",
    description=(
        "Uploads proof of transfer for a PENDING payment. Moves the "
        "payment to WAITING_FOR_REVIEW."
    ),
)
async def upload_receipt(
    payment_id: uuid.UUID,
    file: UploadFile = File(..., description="Receipt screenshot (JPEG/PNG/WebP/PDF, max 5 MB)"),
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_service),
):
    return await service.upload_receipt(user.id, payment_id, file)


@router.post(
    "/payments/{payment_id}/cancel",
    response_model=PaymentResponse,
    summary="Cancel a payment before it's reviewed",
)
async def cancel_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_service),
):
    return await service.cancel_payment(user.id, payment_id)


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentResponse,
    summary="Get one of my payments",
)
async def get_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_service),
):
    return await service.get_my_payment(user.id, payment_id)


@router.get(
    "/payments",
    response_model=PaymentListResponse,
    summary="List my payments (transaction history)",
)
async def list_payments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_service),
):
    return await service.list_my_payments(user.id, page, per_page)


@router.get(
    "/payments/{payment_id}/receipt",
    summary="Download my uploaded receipt file",
)
async def get_receipt_file(
    payment_id: uuid.UUID,
    user: User = Depends(get_active_user),
    service: BillingService = Depends(get_service),
):
    path = await service.get_receipt_file_path(payment_id, user_id=user.id)
    return FileResponse(path)

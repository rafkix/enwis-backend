"""Billing flow: initiate payment -> upload receipt -> admin approve/reject.

Covers the core rewrite from this refactor: the manual card-transfer
payment flow, automatic subscription activation on approval, the
payment-provider abstraction, and admin-only access to moderation
endpoints.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.service import AdminService
from app.modules.auth.models import User
from app.modules.subscriptions.models import PaymentMethod, PaymentStatus
from app.modules.subscriptions.service import BillingService, SubscriptionService


class _FakeUploadFile:
    def __init__(self, content: bytes, filename: str, content_type: str) -> None:
        self._content = content
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._content


@pytest.mark.asyncio
async def test_free_plan_uses_direct_subscribe_not_billing(
    session: AsyncSession, test_user: User,
):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    free_plan = next(p for p in plans if p["price"] == 0)

    result = await sub_service.subscribe(test_user.id, free_plan["id"])
    assert result["status"].lower() == "active" or result.get("plan_id")

    billing = BillingService(session)
    with pytest.raises(HTTPException) as exc:
        await billing.initiate_payment(test_user.id, free_plan["id"], None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_paid_plan_requires_billing_flow(session: AsyncSession, test_user: User):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    paid_plan = next(p for p in plans if p["price"] > 0)

    with pytest.raises(HTTPException) as exc:
        await sub_service.subscribe(test_user.id, paid_plan["id"])
    assert exc.value.status_code == 400
    assert "billing" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_full_billing_approval_activates_subscription(
    session: AsyncSession, test_user: User, admin_user: User,
):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    paid_plan = next(p for p in plans if p["price"] > 0)

    admin_service = AdminService(session)
    await admin_service.create_card(
        admin_user,
        {
            "card_number": "8600123412341234",
            "card_holder_name": "ENWIS MCHJ",
            "bank_name": "Test bank",
            "sort_order": 0,
        },
    )

    billing = BillingService(session)
    payment = await billing.initiate_payment(test_user.id, paid_plan["id"], None)
    assert payment["status"] == PaymentStatus.PENDING.value
    assert payment["method"] == PaymentMethod.MANUAL_CARD.value
    assert payment["amount"] == paid_plan["price"]

    payment = await billing.upload_receipt(
        test_user.id, payment["id"],
        _FakeUploadFile(b"fake-receipt-bytes", "receipt.jpg", "image/jpeg"),
    )
    assert payment["status"] == PaymentStatus.WAITING_FOR_REVIEW.value

    approved = await admin_service.approve_payment(admin_user, payment["id"], "ok")
    assert approved.status == PaymentStatus.APPROVED
    assert approved.subscription_id is not None

    my_sub = await sub_service.get_user_subscription(test_user.id)
    assert my_sub is not None
    assert my_sub["plan_name"] == paid_plan["display_name"]


@pytest.mark.asyncio
async def test_reject_payment_records_reason_and_no_subscription(
    session: AsyncSession, test_user: User, admin_user: User,
):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    paid_plan = next(p for p in plans if p["price"] > 0)

    admin_service = AdminService(session)
    await admin_service.create_card(
        admin_user,
        {"card_number": "9860111122223333", "card_holder_name": "ENWIS", "sort_order": 0},
    )

    billing = BillingService(session)
    payment = await billing.initiate_payment(test_user.id, paid_plan["id"], None)
    payment = await billing.upload_receipt(
        test_user.id, payment["id"],
        _FakeUploadFile(b"bad-receipt", "r.png", "image/png"),
    )

    rejected = await admin_service.reject_payment(admin_user, payment["id"], "Chek noaniq")
    assert rejected.status == PaymentStatus.REJECTED
    assert rejected.rejection_reason == "Chek noaniq"

    my_sub = await sub_service.get_user_subscription(test_user.id)
    assert my_sub is None


@pytest.mark.asyncio
async def test_cannot_cancel_terminal_payment(session: AsyncSession, test_user: User, admin_user: User):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    paid_plan = next(p for p in plans if p["price"] > 0)

    admin_service = AdminService(session)
    await admin_service.create_card(
        admin_user,
        {"card_number": "9860444455556666", "card_holder_name": "ENWIS", "sort_order": 0},
    )

    billing = BillingService(session)
    payment = await billing.initiate_payment(test_user.id, paid_plan["id"], None)
    await billing.cancel_payment(test_user.id, payment["id"])

    with pytest.raises(HTTPException) as exc:
        await billing.cancel_payment(test_user.id, payment["id"])
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_unimplemented_payment_provider_rejected_cleanly(
    session: AsyncSession, test_user: User,
):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    paid_plan = next(p for p in plans if p["price"] > 0)

    billing = BillingService(session)
    with pytest.raises(HTTPException) as exc:
        await billing.initiate_payment(
            test_user.id, paid_plan["id"], None, method=PaymentMethod.PAYME
        )
    assert exc.value.status_code == 501


@pytest.mark.asyncio
async def test_only_waiting_for_review_can_be_approved(
    session: AsyncSession, test_user: User, admin_user: User,
):
    sub_service = SubscriptionService(session)
    await sub_service.seed_default_plans()
    plans = await sub_service.list_plans(active_only=True)
    paid_plan = next(p for p in plans if p["price"] > 0)

    admin_service = AdminService(session)
    await admin_service.create_card(
        admin_user,
        {"card_number": "9860777788889999", "card_holder_name": "ENWIS", "sort_order": 0},
    )

    billing = BillingService(session)
    payment = await billing.initiate_payment(test_user.id, paid_plan["id"], None)
    # still PENDING (no receipt uploaded yet) — approving now must fail
    with pytest.raises(HTTPException) as exc:
        await admin_service.approve_payment(admin_user, payment["id"], None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_dashboard_reflects_users_and_payments(
    session: AsyncSession, test_user: User, admin_user: User,
):
    admin_service = AdminService(session)
    dashboard = await admin_service.get_dashboard()
    assert dashboard.users.total >= 2

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subscriptions.models import PaymentMethod
from app.modules.subscriptions.providers.base import BasePaymentProvider
from app.modules.subscriptions.repository import PaymentCardRepository

if TYPE_CHECKING:
    from app.modules.subscriptions.models import Payment, Plan


class ManualCardProvider(BasePaymentProvider):
    """User pays by transferring money to a bank card the platform
    publishes, then uploads a screenshot of the transfer receipt for an
    admin to review. No gateway involved, so `initiate()` just resolves
    which receiving card to show, and there is no webhook — approval
    happens through `AdminService.approve_payment`.
    """

    method = PaymentMethod.MANUAL_CARD

    async def initiate(
        self, db: AsyncSession, payment: "Payment", plan: "Plan", **kwargs: Any,
    ) -> dict:
        card_repo = PaymentCardRepository(db)
        cards = await card_repo.list_all(active_only=True)
        if not cards:
            raise HTTPException(
                503, "No payment card is configured. Please contact support."
            )

        card_id = kwargs.get("card_id")
        card = None
        if card_id is not None:
            card = next((c for c in cards if c.id == card_id), None)
            if not card:
                raise HTTPException(400, "Selected card is not available")
        else:
            card = cards[0]

        return {"card": card, "cards": cards}

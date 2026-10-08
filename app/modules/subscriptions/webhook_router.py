"""Inbound webhook endpoint for payment gateways.

Real gateways (Payme, Click, Uzcard, ...) confirm a payment by calling
this endpoint server-to-server rather than the user's browser hitting
one of the /billing/payments/* routes. This file is the single landing
point for all of them — the actual verification/parsing logic lives in
each provider's `handle_webhook()` (see providers/base.py), so adding
a gateway never means adding a new route, just registering its
provider.

Not reachable for `manual_card` (there's nothing to call back — an
admin reviews it manually), and every other method currently resolves
to `NotYetImplementedProvider`, so this intentionally 501s until a real
provider is registered.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.subscriptions.models import PaymentMethod
from app.modules.subscriptions.providers import get_provider

router = APIRouter(prefix="/billing/webhooks", tags=["Billing"])


@router.post("/{provider_name}", include_in_schema=False)
async def payment_gateway_webhook(
    provider_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        method = PaymentMethod(provider_name)
    except ValueError:
        raise HTTPException(404, f"Unknown payment provider: {provider_name}")

    provider = get_provider(method)
    if not provider.implemented:
        raise HTTPException(
            501, f"Payment provider '{provider_name}' is not integrated yet."
        )

    payload = await request.json()
    payment = await provider.handle_webhook(db, payload)
    return {"success": True, "payment_id": str(payment.id), "status": payment.status.value}

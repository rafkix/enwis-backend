"""Payment provider abstraction.

Every way a user can pay (today: manual card transfer + admin review;
tomorrow: Payme, Click, Uzcard, ...) implements `BasePaymentProvider`.
`BillingService` only ever talks to providers through this interface,
so adding a new gateway never requires touching BillingService,
routers, or schemas — just:

  1. Add the method to `PaymentMethod` in subscriptions/models.py
     (already reserved: PAYME, CLICK, UZCARD).
  2. Implement a `BasePaymentProvider` subclass in this package.
  3. Register it with `register_provider(...)` in
     `providers/__init__.py`.
  4. Add a webhook route for it if the gateway calls back
     server-to-server (see subscriptions/webhook_router.py).

`ManualCardProvider` (manual_card.py) is the only implemented provider
today: the user is shown a card to transfer to and an admin manually
reviews the uploaded receipt. A gateway provider instead calls out to
the bank/PSP API and gets confirmation via a webhook, but from
BillingService's point of view both look the same: `initiate()` starts
a Payment, and *something* eventually moves it to WAITING_FOR_REVIEW
or straight to APPROVED.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.subscriptions.models import Payment, PaymentMethod, Plan


class PaymentProviderError(Exception):
    """Raised by a provider for gateway-specific failures. BillingService
    turns this into an HTTPException(502, ...) at the API boundary."""


class BasePaymentProvider(ABC):
    """Interface every payment provider must implement."""

    method: "PaymentMethod"
    implemented: bool = True

    @abstractmethod
    async def initiate(
        self, db: "AsyncSession", payment: "Payment", plan: "Plan", **kwargs: Any,
    ) -> dict:
        """Start the payment on the provider's side. Returns whatever the
        client needs to complete it (e.g. a card number to transfer to,
        or a hosted checkout URL for a gateway). Must not change
        `payment.status` itself — the caller (BillingService) owns
        status transitions and the PaymentEvent audit trail.
        """
        raise NotImplementedError

    async def handle_webhook(
        self, db: "AsyncSession", payload: dict,
    ) -> "Payment":
        """Handle an inbound server-to-server callback from the
        provider (payment confirmed/failed/cancelled on their side).
        Only relevant for real gateways — the manual-card provider has
        no webhook, admins review manually instead.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support webhooks"
        )


class NotYetImplementedProvider(BasePaymentProvider):
    """Stand-in for a `PaymentMethod` that's reserved but not built yet
    (Payme/Click/Uzcard). Lets BillingService give a clear 501 instead
    of a confusing KeyError when someone requests it."""

    implemented = False

    def __init__(self, method: "PaymentMethod") -> None:
        self.method = method

    async def initiate(self, db, payment, plan, **kwargs) -> dict:  # noqa: D401
        raise NotImplementedError(
            f"Payment method '{self.method.value}' is not integrated yet. "
            "Use 'manual_card' for now."
        )

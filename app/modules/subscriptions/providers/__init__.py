"""Payment provider registry.

Import `get_provider(method)` to resolve a `PaymentMethod` to its
`BasePaymentProvider` implementation. Unimplemented methods
(PAYME/CLICK/UZCARD today) resolve to `NotYetImplementedProvider`,
which raises a clear NotImplementedError instead of a KeyError.

To wire up a real gateway later:

    # app/modules/subscriptions/providers/payme.py
    class PaymeProvider(BasePaymentProvider):
        method = PaymentMethod.PAYME
        async def initiate(self, db, payment, plan, **kwargs) -> dict:
            ...call Payme's API, return a checkout URL...
        async def handle_webhook(self, db, payload) -> Payment:
            ...verify signature, look up Payment via provider_ref,
               transition its status, return it...

    # here, in providers/__init__.py
    from app.modules.subscriptions.providers.payme import PaymeProvider
    register_provider(PaymeProvider())

Then add a route in subscriptions/webhook_router.py that calls
`get_provider(PaymentMethod.PAYME).handle_webhook(db, payload)`.
"""

from app.modules.subscriptions.models import PaymentMethod
from app.modules.subscriptions.providers.base import (
    BasePaymentProvider,
    NotYetImplementedProvider,
    PaymentProviderError,
)
from app.modules.subscriptions.providers.manual_card import ManualCardProvider

_REGISTRY: dict[PaymentMethod, BasePaymentProvider] = {}


def register_provider(provider: BasePaymentProvider) -> None:
    _REGISTRY[provider.method] = provider


def get_provider(method: PaymentMethod) -> BasePaymentProvider:
    provider = _REGISTRY.get(method)
    if provider is not None:
        return provider
    return NotYetImplementedProvider(method)


register_provider(ManualCardProvider())
# PAYME / CLICK / UZCARD: not registered yet — resolve to
# NotYetImplementedProvider until their provider classes are added.

__all__ = [
    "BasePaymentProvider",
    "NotYetImplementedProvider",
    "PaymentProviderError",
    "get_provider",
    "register_provider",
]

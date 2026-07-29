import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SubscriptionStatus(enum.StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PENDING = "pending"


class PlanInterval(enum.StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(String(20), index=True)
    interval: Mapped[PlanInterval] = mapped_column(
        SAEnum(PlanInterval), default=PlanInterval.MONTHLY
    )
    price: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    max_tests: Mapped[int] = mapped_column(Integer, default=5)
    max_attempts_per_test: Mapped[int] = mapped_column(Integer, default=3)
    max_participants_per_test: Mapped[int] = mapped_column(Integer, default=30)
    ai_generation: Mapped[bool] = mapped_column(default=False)
    advanced_ai: Mapped[bool] = mapped_column(default=False)
    certificate: Mapped[bool] = mapped_column(default=False)
    priority_support: Mapped[bool] = mapped_column(default=False)
    custom_branding: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="plan")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("plans.id"), index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tests_used: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        {"schema": None},
    )


class PaymentMethod(enum.StrEnum):
    """How a Payment is being (or will be) settled.

    Only MANUAL_CARD is implemented today. The others are reserved so
    that adding a real payment gateway later is a matter of adding a
    provider class under `app/modules/subscriptions/providers/` and
    switching this value on — not a schema/model change. See
    `app/modules/subscriptions/providers/base.py`.
    """

    MANUAL_CARD = "manual_card"
    PAYME = "payme"
    CLICK = "click"
    UZCARD = "uzcard"


class PaymentStatus(enum.StrEnum):
    """Lifecycle of a manual card-transfer payment.

    PENDING            -> payment record created, user hasn't uploaded a
                           receipt screenshot yet.
    WAITING_FOR_REVIEW -> receipt screenshot uploaded, waiting for an
                           admin to approve/reject it.
    APPROVED           -> admin approved; the subscription has been
                           activated/renewed automatically.
    REJECTED           -> admin rejected the receipt (invalid/mismatched).
    EXPIRED            -> user never completed the flow in time (no
                           receipt uploaded, or left unreviewed too long).
    CANCELLED          -> user cancelled the payment before it was
                           reviewed.
    """

    PENDING = "pending"
    WAITING_FOR_REVIEW = "waiting_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# Statuses from which a payment can still be moved by the user/admin.
# Anything outside this set is a terminal state.
PAYMENT_ACTIVE_STATUSES = (PaymentStatus.PENDING, PaymentStatus.WAITING_FOR_REVIEW)
PAYMENT_TERMINAL_STATUSES = (
    PaymentStatus.APPROVED,
    PaymentStatus.REJECTED,
    PaymentStatus.EXPIRED,
    PaymentStatus.CANCELLED,
)


class PaymentCard(Base):
    """A receiving bank card the platform accepts manual transfers on.

    Admin-managed. Shown to the user at checkout time so they know where
    to send the payment before uploading a receipt screenshot.
    """

    __tablename__ = "payment_cards"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    card_number: Mapped[str] = mapped_column(String(32))
    card_holder_name: Mapped[str] = mapped_column(String(100))
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Payment(Base):
    """A single manual-transfer payment attempt for a plan purchase.

    Flow: user selects a plan -> Payment(PENDING) is created holding the
    server-computed amount -> user pays externally and uploads a receipt
    screenshot -> Payment moves to WAITING_FOR_REVIEW -> an admin
    approves (subscription auto-activated/renewed) or rejects it.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("plans.id"), index=True
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("payment_cards.id"), nullable=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("user_subscriptions.id"), nullable=True
    )

    # Amount/currency are copied from the Plan at creation time so a later
    # price change on the Plan can never retroactively alter an
    # in-progress or historical payment.
    amount: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus), default=PaymentStatus.PENDING, index=True
    )
    method: Mapped[str] = mapped_column(
        String(20), default=PaymentMethod.MANUAL_CARD.value, index=True
    )
    # Opaque reference from a future gateway (Payme/Click/Uzcard
    # transaction id), so a webhook can look a Payment back up by it.
    # Unused by the manual-card flow.
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    receipt_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receipt_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    admin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Deadline for the user to complete the current step (upload a
    # receipt while PENDING, or wait for review while
    # WAITING_FOR_REVIEW) before the background sweeper marks it EXPIRED.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["Plan"] = relationship()
    card: Mapped["PaymentCard | None"] = relationship()
    subscription: Mapped["UserSubscription | None"] = relationship()
    events: Mapped[list["PaymentEvent"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan",
        order_by="PaymentEvent.created_at",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_payments_user_status", "user_id", "status"),
        Index("ix_payments_status_created", "status", "created_at"),
    )


class PaymentEvent(Base):
    """Immutable transaction-history entry for a Payment.

    One row is written on every status transition (created, receipt
    uploaded, approved, rejected, expired, cancelled), giving a full
    audit trail independent of the mutable Payment row itself.
    """

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    payment: Mapped["Payment"] = relationship(back_populates="events")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

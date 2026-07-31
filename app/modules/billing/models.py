import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid as UuidType

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DiscountType(enum.StrEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


class PromoCodeDiscountType(enum.StrEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


# ── Teacher Package ───────────────────────────────────────────────────


class TeacherPackage(Base):
    """One-time purchase product that grants the TEACHER role forever."""

    __tablename__ = "teacher_packages"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Teacher Package")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class TeacherPurchase(Base):
    """Record of a user purchasing the teacher package.

    Follows the same manual-card-transfer + receipt + admin-review flow
    as the rest of billing (see app.modules.subscriptions.models.Payment):
    pending -> waiting_for_review -> completed/rejected/cancelled/expired.
    The TEACHER role is only granted once an admin approves — this must
    never be set to "completed" by the purchase endpoint itself.
    """

    __tablename__ = "teacher_purchases"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("teacher_packages.id"), nullable=False
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("payment_cards.id"), nullable=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    payment_method: Mapped[str] = mapped_column(String(50), nullable=True)
    payment_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    receipt_image: Mapped[bool] = mapped_column(Boolean, default=False)
    receipt_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    package: Mapped["TeacherPackage"] = relationship()
    user: Mapped["User"] = relationship(foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_teacher_purchases_user", "user_id", "status"),
    )


# ── Pricing Plans ─────────────────────────────────────────────────────


class PricingPlan(Base):
    """Subscription pricing plans: Standard, Pro, Premium.

    These are the core plans that cannot be deleted by admin,
    only updated (name, description, price, active, features).
    """

    __tablename__ = "pricing_plans"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    interval: Mapped[str] = mapped_column(String(20), default="monthly")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    features: Mapped[list["PricingPlanFeature"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )
    discounts: Mapped[list["Discount"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )
    promo_codes: Mapped[list["PromoCode"]] = relationship(
        secondary="promo_code_plans", back_populates="plans", lazy="selectin"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class PricingPlanFeature(Base):
    """Feature list items for a pricing plan."""

    __tablename__ = "pricing_plan_features"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("pricing_plans.id", ondelete="CASCADE"), index=True
    )
    feature: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped["PricingPlan"] = relationship(back_populates="features")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Discount System ───────────────────────────────────────────────────


class Discount(Base):
    """Time-bound percentage discount applied to a specific pricing plan."""

    __tablename__ = "discounts"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("pricing_plans.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    plan: Mapped["PricingPlan"] = relationship(back_populates="discounts")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_discounts_plan_active", "plan_id", "is_active"),
    )


# ── Promo Code System ─────────────────────────────────────────────────


promo_code_plans = Table(
    "promo_code_plans",
    Base.metadata,
    Column("promo_code_id", UuidType, ForeignKey("promo_codes.id", ondelete="CASCADE"), primary_key=True),
    Column("plan_id", UuidType, ForeignKey("pricing_plans.id", ondelete="CASCADE"), primary_key=True),
)


class PromoCodeUsage(Base):
    """Record of a user using a promo code."""

    __tablename__ = "promo_code_usages"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    promo_code: Mapped["PromoCode"] = relationship()

    __table_args__ = (
        Index("ix_promo_code_usages_lookup", "promo_code_id", "user_id"),
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    discount_type: Mapped[PromoCodeDiscountType] = mapped_column(
        SAEnum(PromoCodeDiscountType), default=PromoCodeDiscountType.PERCENTAGE
    )
    discount_value: Mapped[float] = mapped_column(Float, nullable=False)
    usage_limit: Mapped[int] = mapped_column(Integer, default=0)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minimum_amount: Mapped[int] = mapped_column(Integer, default=0)

    plans: Mapped[list["PricingPlan"]] = relationship(
        secondary="promo_code_plans", back_populates="promo_codes", lazy="selectin"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_promo_codes_active_valid", "is_active", "valid_from", "valid_until"),
    )

    @property
    def is_expired(self) -> bool:
        now = datetime.now(UTC)
        return now > self.valid_until

    @property
    def is_usage_exhausted(self) -> bool:
        if self.usage_limit <= 0:
            return False
        return self.used_count >= self.usage_limit

    @property
    def is_valid(self) -> bool:
        now = datetime.now(UTC)
        return (
            self.is_active
            and not self.is_expired
            and not self.is_usage_exhausted
            and now >= self.valid_from
        )


# Import User for relationship
from app.modules.auth.models import User  # noqa: E402, F401

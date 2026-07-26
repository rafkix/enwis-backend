"""Plan tiers and feature gating.

Defines the three subscription tiers (FREE, PRO, PREMIUM) and their
respective limits and feature flags.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class PlanTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"


class PlanLimits:
    """Numeric limits per tier.

    A value of ``-1`` means unlimited.
    """

    FREE: ClassVar[dict[str, int | bool]] = {
        "max_tests": 5,
        "max_attempts_per_test": 5,
        "max_participants_per_test": 30,
        "manual_question_creation": True,
        "excel_import": False,
        "csv_import": False,
        "json_import": False,
        "ai_generation": False,
        "advanced_ai": False,
        "certificate": False,
        "priority_support": False,
    }

    PRO: ClassVar[dict[str, int | bool]] = {
        "max_tests": -1,
        "max_attempts_per_test": -1,
        "max_participants_per_test": 300,
        "manual_question_creation": True,
        "excel_import": True,
        "csv_import": True,
        "json_import": True,
        "ai_generation": True,
        "advanced_ai": False,
        "certificate": True,
        "priority_support": False,
    }

    PREMIUM: ClassVar[dict[str, int | bool]] = {
        "max_tests": -1,
        "max_attempts_per_test": -1,
        "max_participants_per_test": -1,
        "manual_question_creation": True,
        "excel_import": True,
        "csv_import": True,
        "json_import": True,
        "ai_generation": True,
        "advanced_ai": True,
        "certificate": True,
        "priority_support": True,
    }

    @classmethod
    def get_limits(cls, tier: PlanTier) -> dict:
        return getattr(cls, tier.value.upper(), cls.FREE)

    @classmethod
    def get_limit(cls, tier: PlanTier, key: str):
        return cls.get_limits(tier).get(key)

    @classmethod
    def is_unlimited(cls, tier: PlanTier, key: str) -> bool:
        limit = cls.get_limit(tier, key)
        return limit == -1 or limit is None


PLAN_FEATURES = {
    PlanTier.FREE: {
        "name": "Free",
        "description": "Basic access for personal use and trying the platform.",
        "monthly_price": 0,
        "features": [
            "Maximum 5 tests",
            "Maximum 5 attempts per test",
            "Manual question creation",
        ],
    },
    PlanTier.PRO: {
        "name": "Pro",
        "description": "For professional educators and small teams.",
        "monthly_price": 29,
        "features": [
            "Unlimited tests",
            "Unlimited attempts",
            "Excel import",
            "CSV import",
            "JSON import",
            "AI question generation",
        ],
    },
    PlanTier.PREMIUM: {
        "name": "Premium",
        "description": "Full-featured plan with advanced AI and priority support.",
        "monthly_price": 79,
        "features": [
            "Everything in Pro",
            "Advanced AI capabilities",
            "Priority support",
        ],
    },
}


def get_plan_info(tier: PlanTier) -> dict:
    """Return the plan descriptor dict for a given tier."""
    return PLAN_FEATURES.get(tier, PLAN_FEATURES[PlanTier.FREE])


def get_user_plan_tier(tier_str: str | None) -> PlanTier:
    """Convert a database string to a ``PlanTier`` enum."""
    if not tier_str:
        return PlanTier.FREE
    try:
        return PlanTier(tier_str.lower())
    except ValueError:
        return PlanTier.FREE


def get_plan_features(tier: PlanTier) -> dict:
    """Return the feature descriptor dict for a given tier."""
    return PLAN_FEATURES.get(tier, PLAN_FEATURES[PlanTier.FREE])


class PlanLimit:
    """Simple container for numeric plan limits."""

    def __init__(self, max_tests: int | None, max_participants_per_test: int | None):
        self.max_tests = max_tests
        self.max_participants_per_test = max_participants_per_test


def get_plan_limits(tier: PlanTier) -> PlanLimit:
    """Return plan limit values for the given tier."""
    limits = PlanLimits.get_limits(tier)
    return PlanLimit(
        max_tests=limits.get("max_tests"),
        max_participants_per_test=limits.get("max_participants_per_test"),
    )


def check_test_limit(current_count: int, tier: PlanTier) -> bool:
    """Return True if the user may still create another test."""
    limits = PlanLimits.get_limits(tier)
    max_tests = limits.get("max_tests")
    if max_tests == -1 or max_tests is None:
        return True
    return current_count < max_tests


def check_attempt_limit(current_count: int, tier: PlanTier) -> bool:
    """Return True if the user may still take another attempt."""
    limits = PlanLimits.get_limits(tier)
    max_attempts = limits.get("max_attempts_per_test")
    if max_attempts == -1 or max_attempts is None:
        return True
    return current_count < max_attempts


def check_participant_limit(current_count: int, tier: PlanTier) -> bool:
    """Return True if the test may still accept another participant."""
    limits = PlanLimits.get_limits(tier)
    max_p = limits.get("max_participants_per_test")
    if max_p == -1 or max_p is None:
        return True
    return current_count < max_p


def has_feature(tier: PlanTier, feature_key: str) -> bool:
    """Return True if the tier has a given feature enabled."""
    limits = PlanLimits.get_limits(tier)
    return bool(limits.get(feature_key))


def can_use_ai(tier: PlanTier) -> bool:
    return has_feature(tier, "ai_generation")


def can_use_advanced_ai(tier: PlanTier) -> bool:
    return has_feature(tier, "advanced_ai")


def can_use_excel_import(tier: PlanTier) -> bool:
    return has_feature(tier, "excel_import")


def can_use_csv_import(tier: PlanTier) -> bool:
    return has_feature(tier, "csv_import")


def can_use_json_import(tier: PlanTier) -> bool:
    return has_feature(tier, "json_import")

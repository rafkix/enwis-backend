"""Plan tiers and feature gating.

Four tiers:
  FREE     – hech narsa sotib olmagan (bepul)
  TEACHER  – bir martalik to'lov (TeacherPackage), lifetime rol
  PRO      – oylik/yillik obuna
  PREMIUM  – oylik/yillik obuna

AI limiti oylik hisoblanadi (ai_questions_used + ai_questions_reset_at).
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class PlanTier(StrEnum):
    FREE = "free"
    TEACHER = "teacher"
    PRO = "pro"
    PREMIUM = "premium"


class PlanLimits:
    """Numeric limits per tier.

    A value of ``-1`` means unlimited.

    ``ai_questions_per_month``:
        0   = AI yo'q
        N   = oyiga N ta savol generatsiya qilish mumkin
        -1  = cheksiz
    """

    FREE: ClassVar[dict[str, int | bool]] = {
        "max_tests": 10,
        "max_participants_per_test": 30,
        "ai_generation": False,
        "ai_questions_per_month": 0,
        "advanced_ai": False,
        "exam_access": False,
        "student_management": False,
        "certificate": False,
        "priority_support": False,
        "csv_import": False,
        "excel_import": False,
    }

    TEACHER: ClassVar[dict[str, int | bool]] = {
        "max_tests": 10,
        "max_participants_per_test": 30,
        "ai_generation": True,
        "ai_questions_per_month": 10,
        "advanced_ai": False,
        "exam_access": True,
        "student_management": True,
        "certificate": False,
        "priority_support": False,
        "csv_import": True,
        "excel_import": True,
    }

    PRO: ClassVar[dict[str, int | bool]] = {
        "max_tests": 100,
        "max_participants_per_test": 500,
        "ai_generation": True,
        "ai_questions_per_month": 50,
        "advanced_ai": False,
        "exam_access": True,
        "student_management": True,
        "certificate": False,
        "priority_support": False,
        "csv_import": True,
        "excel_import": True,
    }

    PREMIUM: ClassVar[dict[str, int | bool]] = {
        "max_tests": -1,
        "max_participants_per_test": -1,
        "ai_generation": True,
        "ai_questions_per_month": 100,
        "advanced_ai": True,
        "exam_access": True,
        "student_management": True,
        "certificate": True,
        "priority_support": True,
        "csv_import": True,
        "excel_import": True,
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
        "name": "Bepul",
        "description": "Sinab ko'rish uchun asosiy kirish.",
        "monthly_price": 0,
        "features": [
            "10 tagacha test yaratish",
            "Har bir testga 30 tagacha ishtirokchi",
            "Avtomatik baholash",
            "Testni havola orqali ulashish",
            "Community qo'llab-quvvatlash",
        ],
    },
    PlanTier.TEACHER: {
        "name": "Teacher",
        "description": "Bir martalik to'lov — umrbod o'qituvchi kirishi.",
        "monthly_price": 0,  # bir martalik narx TeacherPackage.price
        "features": [
            "10 tagacha test yaratish",
            "Har bir testga 30 tagacha ishtirokchi",
            "AI savol generatori (oyiga 10 ta)",
            "Imtihon (exam) o'tkazish",
            "O'quvchilarni boshqarish va baholash",
            "Avtomatik baholash",
            "Batafsil statistika",
        ],
    },
    PlanTier.PRO: {
        "name": "Pro",
        "description": "Professional o'qituvchilar va kichik jamoalar uchun.",
        "monthly_price": 99000,
        "features": [
            "100 tagacha test yaratish",
            "Har bir testga 500 tagacha ishtirokchi",
            "AI savol generatori (oyiga 50 ta)",
            "Savollar banki",
            "Imtihon (exam) o'tkazish",
            "O'quvchilarni boshqarish va baholash",
            "Avtomatik baholash",
            "Batafsil statistika",
            "Guruhlarni boshqarish",
            "Email qo'llab-quvvatlash",
        ],
    },
    PlanTier.PREMIUM: {
        "name": "Premium",
        "description": "To'liq imkoniyatlar, kengaytirilgan AI va prioritet yordam.",
        "monthly_price": 199000,
        "features": [
            "Cheksiz test yaratish",
            "Cheksiz ishtirokchilar",
            "AI savol generatori (oyiga 100 ta)",
            "AI natijalar tahlili",
            "Sertifikat yaratish",
            "Savollar banki",
            "Imtihon (exam) o'tkazish",
            "O'quvchilarni boshqarish va baholash",
            "Guruhlarni boshqarish",
            "Prioritet texnik yordam",
            "Yangi funksiyalarga erta kirish",
        ],
    },
}


def get_plan_info(tier: PlanTier) -> dict:
    """Return the plan descriptor dict for a given tier."""
    return PLAN_FEATURES.get(tier, PLAN_FEATURES[PlanTier.FREE])


def get_user_plan_tier(tier_str: str | None) -> PlanTier:
    """Convert a database string to a PlanTier enum."""
    if not tier_str:
        return PlanTier.FREE
    try:
        return PlanTier(tier_str.lower())
    except ValueError:
        return PlanTier.FREE


def get_plan_features(tier: PlanTier) -> dict:
    return PLAN_FEATURES.get(tier, PLAN_FEATURES[PlanTier.FREE])


class PlanLimit:
    def __init__(self, max_tests: int | None, max_participants_per_test: int | None):
        self.max_tests = max_tests
        self.max_participants_per_test = max_participants_per_test


def get_plan_limits(tier: PlanTier) -> PlanLimit:
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


def check_participant_limit(current_count: int, tier: PlanTier) -> bool:
    """Return True if the test may still accept another participant."""
    limits = PlanLimits.get_limits(tier)
    max_p = limits.get("max_participants_per_test")
    if max_p == -1 or max_p is None:
        return True
    return current_count < max_p


def has_feature(tier: PlanTier, feature_key: str) -> bool:
    limits = PlanLimits.get_limits(tier)
    return bool(limits.get(feature_key))


def can_use_ai(tier: PlanTier) -> bool:
    """Tier AI generatsiyaga ruxsat beradimi."""
    return has_feature(tier, "ai_generation")


def can_use_advanced_ai(tier: PlanTier) -> bool:
    return has_feature(tier, "advanced_ai")


def get_ai_monthly_limit(tier: PlanTier) -> int:
    """Oyiga nechta AI savol yaratish mumkin. 0 = yo'q, -1 = cheksiz."""
    limits = PlanLimits.get_limits(tier)
    return int(limits.get("ai_questions_per_month", 0))


def can_access_exams(tier: PlanTier) -> bool:
    return has_feature(tier, "exam_access")


def can_manage_students(tier: PlanTier) -> bool:
    return has_feature(tier, "student_management")


def can_create_certificate(tier: PlanTier) -> bool:
    return has_feature(tier, "certificate")


def can_use_csv_import(tier: PlanTier) -> bool:
    """Tier CSV orqali savol import qilishga ruxsat beradimi."""
    return has_feature(tier, "csv_import")


def can_use_excel_import(tier: PlanTier) -> bool:
    """Tier Excel orqali savol import qilishga ruxsat beradimi."""
    return has_feature(tier, "excel_import")

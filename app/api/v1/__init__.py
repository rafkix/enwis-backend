"""API v1 — the current stable, publicly-documented API generation.

`v1_router` aggregates every module's router. It carries NO prefix of
its own (`app/main.py` applies `settings.API_PREFIX`, i.e. "/api/v1",
when it mounts this router) so the same module routers could in
principle also be reused unmodified under `/api/v2` for endpoints that
don't change between versions (see `app/api/v2/__init__.py`).
"""

from fastapi import APIRouter

from app.modules.admin import admin_router
from app.modules.auth import auth_router
from app.modules.billing import billing_router as billing_module_router
from app.modules.dashboard import dashboard_router, public_router
from app.modules.notifications import notifications_router
from app.modules.subscriptions import billing_router, subscriptions_router, webhook_router
from app.modules.tests import tests_management_router, tests_public_router
from app.modules.users import users_router

# NOTE: Exams module (exams.enwis.uz — official exams/certificates/apply)
# is TEMPORARILY DISABLED at the API level per product decision — will be
# rebuilt and re-enabled later. The underlying package (app/modules/exams)
# is intentionally NOT deleted: app.modules.tests.service,
# app.modules.dashboard.service, and app.modules.admin.service all still
# import Exam/ExamAttempt/Certificate models from it for statistics. Only
# the exams_router / apply_router / certificates_router (the public API
# surface) are left unregistered below.

v1_router = APIRouter()

_v1_module_routers = [
    # ── User & Auth ──────────────────────────────────────────────
    users_router,
    auth_router,
    # ── Dashboard ────────────────────────────────────────────────
    dashboard_router,
    public_router,
    # ── Exams: DISABLED for now (exams.enwis.uz rebuild pending) ───
    # exams_router,
    # apply_router,
    # certificates_router,
    # ── Tests: split by front-end ───────────────────────────────────
    # app.enwis.uz — authoring/management (create, edit, AI-generate,
    # import/export, settings, publish)
    tests_management_router,
    # test.enwis.uz — public discovery + practice-taking
    # (Google/Telegram login only)
    tests_public_router,
    # ── Billing module (pricing, discounts, promo codes, teacher package) ──
    billing_module_router,
    # ── Notifications ────────────────────────────────────────────
    notifications_router,
    # ── Subscriptions & billing ───────────────────────────────────
    subscriptions_router,
    billing_router,
    webhook_router,
    # ── Admin panel ──────────────────────────────────────────────
    admin_router,
]

for _router in _v1_module_routers:
    v1_router.include_router(_router)

__all__ = ["v1_router"]

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.middleware import RequestLoggerMiddleware

# ── Module imports ───────────────────────────────────────────────────
from app.modules.auth import auth_router
from app.modules.auth.models import Role
from app.modules.dashboard import dashboard_router, public_router

# NOTE: Exams module (exams.enwis.uz — official exams/certificates/apply)
# is TEMPORARILY DISABLED at the API level per product decision — will be
# rebuilt and re-enabled later. The underlying package (app/modules/exams)
# is intentionally NOT deleted: app.modules.tests.service and
# app.modules.dashboard.service both still import Exam/ExamAttempt/
# Certificate models from it for statistics. Only the exams_router /
# apply_router / certificates_router (the public API surface) are
# unregistered below.
from app.modules.notifications import notifications_router
from app.modules.subscriptions import subscriptions_router
from app.modules.tests import tests_management_router, tests_public_router

# ── User & Auth ──────────────────────────────────────────────────────
from app.modules.users import users_router

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def _seed_roles() -> None:
    async with AsyncSessionLocal() as db:
        for name, desc in [
            ("USER", "Default user"),
            ("ADMIN", "System administrator"),
            ("TEACHER", "Teacher role"),
        ]:
            result = await db.execute(select(Role).where(Role.name == name))
            if not result.scalar_one_or_none():
                db.add(Role(name=name, description=desc))
        await db.commit()


async def _placeholder_checker_loop() -> None:
    """Placeholder background task — will be replaced with real subscription/quota logic."""
    while True:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("Background checker cancelled")
            break
        except Exception:
            logger.exception("Error in background checker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Enwis Backend API...")
    await init_db()
    await _seed_roles()
    logger.info("Database initialized")

    checker_task = asyncio.create_task(_placeholder_checker_loop())
    try:
        yield
    finally:
        logger.info("Shutting down application...")
        checker_task.cancel()
        try:
            await checker_task
        except asyncio.CancelledError:
            logger.info("Background checker stopped")


app = FastAPI(
    title="Enwis Backend API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs" if settings.DEBUG else None,
    redoc_url="/api/v1/redoc" if settings.DEBUG else None,
    description="Enwis is an AI-powered IELTS and CEFR preparation platform.",
)

origins = list(
    set(
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "https://unbend-unfilled-overlaid.ngrok-free.dev",
            "https://enwis.uz",
            "https://app.enwis.uz",
            "https://api.enwis.uz",
            *(settings.ALLOWED_ORIGINS or []),
        ]
    )
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.JWT_SECRET)
app.add_middleware(RequestLoggerMiddleware)


class PublicStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path.replace("\\", "/").startswith("payment-proofs/"):
            raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)


os.makedirs("static/audio", exist_ok=True)
app.mount("/static", PublicStaticFiles(directory="static"), name="static")

API_PREFIX = "/api/v1"

for router in [
    # ── User & Auth ──────────────────────────────────────────────────
    users_router,
    auth_router,
    # ── Dashboard ────────────────────────────────────────────────────
    dashboard_router,
    public_router,
    # ── Exams: DISABLED for now (exams.enwis.uz rebuild pending) ──────
    # exams_router,
    # apply_router,
    # certificates_router,
    # ── Tests: split by front-end ──────────────────────────────────────
    # app.enwis.uz — authoring/management (create, edit, AI-generate,
    # import/export, settings, publish)
    tests_management_router,
    # test.enwis.uz — public discovery + practice-taking
    # (Google/Telegram login only)
    tests_public_router,
    # ── Notifications ────────────────────────────────────────────────
    notifications_router,
    # ── Subscriptions ────────────────────────────────────────────────
    subscriptions_router,
]:
    app.include_router(router, prefix=API_PREFIX)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "status_code": exc.status_code,
                "detail": exc.detail,
                "path": str(request.url),
            },
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled server error",
        extra={"path": str(request.url), "method": request.method},
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "status_code": 500,
                "detail": "Internal Server Error",
                "path": str(request.url),
            },
        },
    )


@app.get("/", include_in_schema=False)
async def root():
    return {
        "success": True,
        "message": "Enwis Backend API is running",
        "version": "1.0.0",
    }


@app.get("/health", tags=["System"])
async def health_check():
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"success": True, "status": "healthy", "database": "connected"}
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "unhealthy",
                "database": "disconnected",
            },
        )


if __name__ == "__main__":
    import uvicorn

    # This __main__ block is only ever used for local development
    # (`python -m app.main`). Production should run uvicorn/gunicorn
    # directly without --reload, so hardcoding reload=True here is safe
    # and avoids depending on settings.DEBUG being read correctly.
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["app"],
        reload_excludes=[".venv", "static", "__pycache__", "*.pyc"],
    )

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.middleware import RequestLoggerMiddleware, SecurityHeadersMiddleware

# ── Versioned API aggregators ────────────────────────────────────────
# See app/api/v1/__init__.py and app/api/v2/__init__.py: each URL-routing
# generation owns exactly one aggregate router, so adding /api/v2 later
# never means touching this file's routing logic again — only adding a
# new app/api/vN package and mounting it below.
from app.api.v1 import v1_router
from app.api.v2 import v2_router
from app.modules.auth.models import Role
from app.modules.subscriptions.service import BillingService

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


PAYMENT_SWEEP_INTERVAL_SECONDS = 15 * 60  # every 15 minutes


async def _payment_expiry_sweep_loop() -> None:
    """Periodically expires PENDING payments whose receipt-upload
    deadline passed, and WAITING_FOR_REVIEW payments an admin never
    reviewed in time (see subscriptions/constants.py timeouts)."""
    while True:
        try:
            await asyncio.sleep(PAYMENT_SWEEP_INTERVAL_SECONDS)
            async with AsyncSessionLocal() as db:
                expired_count = await BillingService(db).sweep_expired_payments()
                if expired_count:
                    logger.info("Payment sweep: expired %s payment(s)", expired_count)
        except asyncio.CancelledError:
            logger.info("Payment expiry sweeper cancelled")
            break
        except Exception:
            logger.exception("Error in payment expiry sweeper")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Enwis Backend API...")
    await init_db()
    await _seed_roles()
    logger.info("Database initialized")

    checker_task = asyncio.create_task(_payment_expiry_sweep_loop())
    try:
        yield
    finally:
        logger.info("Shutting down application...")
        checker_task.cancel()
        try:
            await checker_task
        except asyncio.CancelledError:
            logger.info("Payment expiry sweeper stopped")


app = FastAPI(
    title="Enwis Backend API",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    # Standart docs/redoc/openapi o'chirilgan — pastda o'rniga parol bilan
    # himoyalangan versiyalari qo'shilgan (DEBUG holatidan qat'i nazar,
    # har doim login/parol so'raladi, doim ochiq turmaydi).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    description="Enwis is an AI-powered test creation, delivery, and assessment platform.",
)

_docs_session_key = "docs_auth"

_DOCS_LOGIN_PAGE = """<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>API Docs — Kirish</title>
<style>
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; background: #0f172a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  form {{
    background: #fff; padding: 32px; border-radius: 16px; width: 320px;
    box-shadow: 0 20px 60px rgba(0,0,0,.35);
  }}
  h1 {{ font-size: 18px; margin: 0 0 20px; color: #0f172a; }}
  label {{ display: block; font-size: 13px; color: #475569; margin: 12px 0 4px; }}
  input {{
    width: 100%; box-sizing: border-box; padding: 9px 11px; font-size: 14px;
    border: 1px solid #e2e8f0; border-radius: 8px; outline: none;
  }}
  input:focus {{ border-color: #0f172a; }}
  button {{
    width: 100%; margin-top: 20px; padding: 10px; font-size: 14px;
    font-weight: 600; color: #fff; background: #0f172a; border: none;
    border-radius: 8px; cursor: pointer;
  }}
  button:hover {{ background: #1e293b; }}
  .err {{ color: #dc2626; font-size: 13px; margin: 0 0 8px; }}
</style>
</head>
<body>
  <form method="post" action="{prefix}/docs/login">
    <h1>API hujjatlariga kirish</h1>
    {error_html}
    <input type="hidden" name="next" value="{next}" />
    <label>Login</label>
    <input type="text" name="username" autocomplete="username" required autofocus />
    <label>Parol</label>
    <input type="password" name="password" autocomplete="current-password" required />
    <button type="submit">Kirish</button>
  </form>
</body>
</html>"""


def _docs_authed(request: Request) -> bool:
    return bool(request.session.get(_docs_session_key))


@app.get(f"{settings.API_PREFIX}/docs/login", include_in_schema=False)
async def docs_login_form(next: str = f"{settings.API_PREFIX}/docs", error: int = 0):
    error_html = (
        '<p class="err">Login yoki parol noto\'g\'ri</p>' if error else ""
    )
    return HTMLResponse(
        _DOCS_LOGIN_PAGE.format(
            prefix=settings.API_PREFIX, next=next, error_html=error_html
        )
    )


@app.post(f"{settings.API_PREFIX}/docs/login", include_in_schema=False)
async def docs_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(f"{settings.API_PREFIX}/docs"),
):
    """secrets.compare_digest — timing attack'lardan himoya qiladi (oddiy
    == solishtirish emas)."""
    valid_username = secrets.compare_digest(username, settings.DOCS_USERNAME)
    valid_password = secrets.compare_digest(password, settings.DOCS_PASSWORD)
    if not (valid_username and valid_password):
        return RedirectResponse(
            url=f"{settings.API_PREFIX}/docs/login?next={next}&error=1",
            status_code=303,
        )
    request.session[_docs_session_key] = True
    return RedirectResponse(url=next, status_code=303)


@app.get(f"{settings.API_PREFIX}/docs/logout", include_in_schema=False)
async def docs_logout(request: Request):
    request.session.pop(_docs_session_key, None)
    return RedirectResponse(url=f"{settings.API_PREFIX}/docs/login")


@app.get(f"{settings.API_PREFIX}/openapi.json", include_in_schema=False)
async def get_openapi_schema(request: Request):
    if not _docs_authed(request):
        return RedirectResponse(
            url=f"{settings.API_PREFIX}/docs/login?next={settings.API_PREFIX}/openapi.json"
        )
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@app.get(f"{settings.API_PREFIX}/docs", include_in_schema=False)
async def get_docs(request: Request):
    if not _docs_authed(request):
        return RedirectResponse(
            url=f"{settings.API_PREFIX}/docs/login?next={settings.API_PREFIX}/docs"
        )
    return get_swagger_ui_html(
        openapi_url=f"{settings.API_PREFIX}/openapi.json", title=f"{app.title} — Docs"
    )


@app.get(f"{settings.API_PREFIX}/redoc", include_in_schema=False)
async def get_redoc(request: Request):
    if not _docs_authed(request):
        return RedirectResponse(
            url=f"{settings.API_PREFIX}/docs/login?next={settings.API_PREFIX}/redoc"
        )
    return get_redoc_html(
        openapi_url=f"{settings.API_PREFIX}/openapi.json", title=f"{app.title} — ReDoc"
    )


origins = list(
    set(
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "https://enwis.uz",
            "https://app.enwis.uz",
            "https://test.enwis.uz",
            "https://exams.enwis.uz",
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
app.add_middleware(SecurityHeadersMiddleware)


class PublicStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path.replace("\\", "/").startswith("payment-proofs/"):
            raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)


os.makedirs("static/audio", exist_ok=True)
os.makedirs("static/payment-proofs", exist_ok=True)
app.mount("/static", PublicStaticFiles(directory="static"), name="static")

# ── Versioned API mounting ────────────────────────────────────────────
# /api/v1 is the current stable, fully-implemented API generation.
# /api/v2 is mounted too (see app/api/v2) so the URL space is reserved
# and the pattern is proven end-to-end, but it has no real endpoints
# yet — see that module's docstring for how to add them.
app.include_router(v1_router, prefix=settings.API_PREFIX)
app.include_router(v2_router, prefix="/api/v2")


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
        "version": settings.APP_VERSION,
        "api_version": settings.API_VERSION,
        "api_prefix": settings.API_PREFIX,
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
"""FastAPI application entry point."""

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from pathlib import Path

from ess.config import get_settings
from ess.web import admin, admin_ecp, admin_members, admin_org, admin_payments, auth, portal, public
from ess.web.templates import templates

logger = logging.getLogger(__name__)


def _session_secret() -> str:
    settings = get_settings()
    if settings.session_secret:
        return settings.session_secret
    if settings.environment == "prod":
        raise RuntimeError("ESS_SESSION_SECRET must be set in production")
    logger.warning("ESS_SESSION_SECRET is not set - using a random secret (sessions reset on restart)")
    return secrets.token_urlsafe(48)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="eSpeleoSociety",
        # Interactive API docs only outside production.
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "prod" else None,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(),
        session_cookie="ess_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        # Cookie only over HTTPS whenever the app is served over HTTPS (Cloud Run, production).
        https_only=settings.environment == "prod" or (settings.public_base_url or "").startswith("https://"),
    )
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(auth.router)
    # Specific routes (/members/new, /clubs/new) before parametrised ones.
    app.include_router(admin_members.router)
    app.include_router(admin_org.router)
    app.include_router(admin_ecp.router)
    app.include_router(admin_payments.router)
    app.include_router(admin.router)
    app.include_router(public.router)
    app.include_router(public.verify_router)
    app.include_router(portal.router)

    @app.exception_handler(auth.LoginRequired)
    async def _login_required(request: Request, exc: auth.LoginRequired):
        return templates.TemplateResponse(request, "admin/login.html", {}, status_code=401)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"environment": settings.environment})

    @app.get("/healthz")
    def healthz():
        """Liveness: the process is running (no external dependencies)."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        """Readiness: the database is reachable."""
        from ess.db import get_engine

        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "unavailable", "database": "error"}, status_code=503)
        return {"status": "ok", "database": "ok"}

    return app


app = create_app()

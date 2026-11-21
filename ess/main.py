"""FastAPI application entry point."""

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path

from ess.config import get_settings
from ess.web import admin, admin_ecp, admin_members, admin_org, admin_payments, auth, portal, portal_chair, public
from ess.web.headers import SecurityHeaders, static_app
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
    # Interactive API docs only for local development: never on a public (https) deployment, whatever
    # ESS_ENVIRONMENT says; the administration is never listed in them (include_in_schema=False below).
    api_docs = settings.environment == "dev" and not (settings.public_base_url or "").startswith("https://")
    app = FastAPI(
        title="eSpeleoSociety",
        docs_url="/docs" if api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if api_docs else None,
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
    https = settings.environment == "prod" or (settings.public_base_url or "").startswith("https://")
    app.add_middleware(SecurityHeaders, hsts=https)  # outermost: also on error pages
    app.mount("/static", static_app(Path(__file__).parent / "static"), name="static")
    # Administration under its own path (R48); specific routes (/members/new) before parametrised ones.
    admin_prefix = "/" + settings.admin_path
    if settings.environment == "prod" and settings.admin_path == "admin":
        logger.warning("ESS_ADMIN_PATH is not set - the administration is at the guessable /admin")
    for module in (auth, admin_members, admin_org, admin_ecp, admin_payments, admin):
        app.include_router(module.router, prefix=admin_prefix, include_in_schema=False)  # never in /openapi.json
    app.include_router(public.router)
    app.include_router(public.verify_router)
    app.include_router(portal_chair.router)
    app.include_router(portal.router)

    @app.exception_handler(auth.NotAllowed)
    async def _not_allowed(request: Request, exc: auth.NotAllowed):
        return templates.TemplateResponse(request, "admin/forbidden.html", {"admin": exc.admin}, status_code=403)

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

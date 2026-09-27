"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from ess.config import get_settings

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="eSpeleoSociety",
        # Interactive API docs only outside production.
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "prod" else None,
    )

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

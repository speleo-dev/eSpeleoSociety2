"""Security and cache headers for every response, and compressed, cacheable static files."""

from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# A partial Content-Security-Policy that cannot break the pages: no framing (clickjacking), no plugins,
# forms and <base> only to this site. Scripts are not restricted yet (inline scripts still exist).
CSP = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"

STATIC_PREFIX = "/static/"
VENDOR_MAX_AGE = 7 * 24 * 3600  # Tabler, icons, HTMX: change only with an upgrade
STATIC_MAX_AGE = 3600  # our own CSS/JS/images: a new deploy is picked up within an hour


class SecurityHeaders:
    """Pure ASGI middleware (no buffering of responses)."""

    def __init__(self, app: ASGIApp, hsts: bool):
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "same-origin")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Content-Security-Policy", CSP)
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
                if path.startswith(STATIC_PREFIX):
                    max_age = VENDOR_MAX_AGE if path.startswith(STATIC_PREFIX + "vendor/") else STATIC_MAX_AGE
                    headers.setdefault("Cache-Control", f"public, max-age={max_age}")
                else:
                    # Pages carry personal data: never stored by the browser or a proxy (back button, shared PC).
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


def static_app(directory) -> ASGIApp:
    """Static files, gzip-compressed (Tabler CSS ~680 kB -> ~90 kB). Only static files are compressed:
    pages mix secrets (CSRF token) with reflected input, which compression could leak (BREACH)."""
    return GZipMiddleware(StaticFiles(directory=directory), minimum_size=1000)

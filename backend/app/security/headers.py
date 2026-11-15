"""Security headers on every response."""

from fastapi import FastAPI, Request

from app.config import get_settings

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def install_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith(DOC_PATHS):
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if get_settings().cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

"""
Security middleware: CSP, CORS, rate-limiting, request validation.
"""
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from ..core.tokens import check_rate_limit
import os

ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
]

# Pages that legitimately need camera access
CAMERA_PAGES = {"/admin", "/listen"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject strict security headers on every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        path = request.url.path

        # Allow camera on admin and listen pages; block everywhere else
        needs_camera = path == "/admin" or path.startswith("/listen/")
        camera_policy = "camera=*" if needs_camera else "camera=()"

        response.headers["X-Content-Type-Options"]   = "nosniff"
        response.headers["X-Frame-Options"]           = "DENY"
        response.headers["X-XSS-Protection"]          = "1; mode=block"
        response.headers["Referrer-Policy"]            = "no-referrer"
        response.headers["Permissions-Policy"]         = (
            f"{camera_policy}, microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"]   = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' ws: wss: https://cdn.jsdelivr.net; "
            "media-src 'self' blob:; "
            "img-src 'self' data: blob:; "
            "worker-src blob:;"
        )
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Cache-Control"]              = "no-store, no-cache"
        response.headers["Pragma"]                     = "no-cache"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting on API routes."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            if not check_rate_limit(ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please wait."},
                )
        return await call_next(request)


def setup_cors(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Session-ID"],
    )
from __future__ import annotations

from fastapi import Request, Response


DASHBOARD_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
        "connect-src 'self'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' 'unsafe-inline'",
    ]
)


def harden_response_headers(request: Request, response: Response) -> Response:
    """Apply secret-free browser hardening without changing application behavior.

    Browser-oriented dashboard routes receive a restrictive CSP and explicit
    no-store directives. Baseline headers are safe for the JSON/API surface too.
    Inline CSS/JavaScript is currently part of the intentionally small dashboard,
    so CSP permits inline style/script until those assets are externalized.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault(
        "Strict-Transport-Security",
        "max-age=31536000; includeSubDomains",
    )

    if request.url.path.startswith("/dashboard"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Content-Security-Policy"] = DASHBOARD_CONTENT_SECURITY_POLICY
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

    return response

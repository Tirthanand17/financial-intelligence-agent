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
    """Apply secret-free browser and protected-read-API hardening."""
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

    path = request.url.path
    if path.startswith("/dashboard"):
        # Preserve the established dashboard API cache contract while also
        # protecting HTML and authentication-error responses consistently.
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Content-Security-Policy"] = DASHBOARD_CONTENT_SECURITY_POLICY
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    elif path == "/api/v1" or path.startswith("/api/v1/"):
        # The versioned API exposes private persisted evidence. Keep successful,
        # validation-error, not-found, and authentication-error responses out of
        # browser/proxy caches without applying the HTML dashboard CSP to JSON.
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    return response

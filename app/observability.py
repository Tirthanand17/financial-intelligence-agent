from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar, Token
from typing import Any

from fastapi import Request, Response


_REQUEST_ID: ContextVar[str | None] = ContextVar("financial_intelligence_request_id", default=None)
logger = logging.getLogger("financial_intelligence.request")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def current_request_id() -> str | None:
    """Return the server-generated request correlation id for the current context."""
    return _REQUEST_ID.get()


def _runtime_context() -> dict[str, str]:
    """Return non-secret deployment/run correlation metadata when available."""
    mapping = {
        "git_commit": os.getenv("RENDER_GIT_COMMIT"),
        "render_instance": os.getenv("RENDER_INSTANCE_ID"),
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "github_workflow": os.getenv("GITHUB_WORKFLOW"),
    }
    return {key: value for key, value in mapping.items() if value}


def build_request_log_record(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int | None,
    duration_ms: float,
    outcome: str,
    exception_type: str | None = None,
) -> dict[str, Any]:
    """Build a secret-minimized structured request event.

    Query strings, request/response bodies, Authorization/Cookie headers, client IPs,
    usernames and exception messages are intentionally excluded.
    """
    record: dict[str, Any] = {
        "event": "http_request",
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": round(max(duration_ms, 0.0), 3),
        "outcome": outcome,
        **_runtime_context(),
    }
    if exception_type:
        record["exception_type"] = exception_type
    return record


async def observe_http_request(request: Request, call_next) -> Response:
    """Attach a server-generated request id and emit one JSON event per request."""
    request_id = uuid.uuid4().hex
    token: Token[str | None] = _REQUEST_ID.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                build_request_log_record(
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=int(response.status_code),
                    duration_ms=duration_ms,
                    outcome="completed",
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000.0
        logger.error(
            json.dumps(
                build_request_log_record(
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=None,
                    duration_ms=duration_ms,
                    outcome="exception",
                    exception_type=type(exc).__name__,
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise
    finally:
        _REQUEST_ID.reset(token)

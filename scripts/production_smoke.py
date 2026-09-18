from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://financial-intelligence-dashboard-z6fj.onrender.com"
PROTECTED_PATHS = (
    "/dashboard/hub",
    "/dashboard",
    "/dashboard/readiness",
    "/dashboard/incidents",
    "/dashboard/intelligence-view",
    "/dashboard/verification",
    "/dashboard/quality-coverage",
    "/dashboard/quality-scorecards",
    "/dashboard/indicator-catalog",
    "/dashboard/timeline",
    "/dashboard/changes",
    "/dashboard/search",
    "/dashboard/export",
    "/dashboard/document",
    "/dashboard/conflicts",
    "/dashboard/provenance",
)
REQUIRED_DASHBOARD_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@dataclass(frozen=True, slots=True)
class SmokeResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


def _normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _valid_request_id(value: str | None) -> bool:
    if value is None or len(value) != 32:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def validate_health(response: SmokeResponse) -> list[str]:
    errors: list[str] = []
    headers = _normalized_headers(response.headers)
    if response.status != 200:
        errors.append(f"health_status={response.status}")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if payload != {"status": "ok"}:
        errors.append("health_payload_invalid")
    if headers.get("x-content-type-options") != "nosniff":
        errors.append("health_missing_nosniff")
    if not _valid_request_id(headers.get("x-request-id")):
        errors.append("health_request_id_invalid")
    return errors


def validate_dashboard_response(response: SmokeResponse, *, authenticated: bool) -> list[str]:
    errors: list[str] = []
    headers = _normalized_headers(response.headers)
    expected_status = 200 if authenticated else 401
    if response.status != expected_status:
        errors.append(f"status={response.status},expected={expected_status}")
    if "no-store" not in headers.get("cache-control", "").lower():
        errors.append("cache_control_not_no_store")
    if "content-security-policy" not in headers:
        errors.append("missing_csp")
    for key, expected in REQUIRED_DASHBOARD_HEADERS.items():
        if headers.get(key) != expected:
            errors.append(f"header_{key}_invalid")
    if not _valid_request_id(headers.get("x-request-id")):
        errors.append("request_id_invalid")
    if not authenticated and "basic" not in headers.get("www-authenticate", "").lower():
        errors.append("missing_basic_auth_challenge")
    return errors


def _request(base_url: str, path: str, *, username: str | None = None, password: str | None = None) -> SmokeResponse:
    headers = {"User-Agent": "financial-intelligence-agent-production-smoke/1"}
    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = Request(base_url.rstrip("/") + path, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed operator-controlled HTTPS URL
            return SmokeResponse(status=int(response.status), headers=dict(response.headers.items()), body=response.read(1_000_000))
    except HTTPError as exc:
        return SmokeResponse(status=int(exc.code), headers=dict(exc.headers.items()), body=exc.read(1_000_000))


def main() -> int:
    base_url = os.getenv("PRODUCTION_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.startswith("https://"):
        print("FINAL: BLOCKED - production smoke base URL must use HTTPS.")
        return 2
    username = os.getenv("DASHBOARD_USERNAME") or None
    password = os.getenv("DASHBOARD_PASSWORD") or None
    if (username is None) != (password is None):
        print("FINAL: BLOCKED - dashboard smoke credentials are only accepted as a complete pair.")
        return 2
    failures: list[str] = []
    try:
        health = _request(base_url, "/health")
        failures.extend(f"/health:{error}" for error in validate_health(health))
        print(f"HEALTH: status={health.status}")
        for path in PROTECTED_PATHS:
            unauthenticated = _request(base_url, path)
            failures.extend(f"{path}:unauthenticated:{error}" for error in validate_dashboard_response(unauthenticated, authenticated=False))
            print(f"PROTECTED: path={path} unauthenticated_status={unauthenticated.status}")
            if username is not None and password is not None:
                authenticated_response = _request(base_url, path, username=username, password=password)
                failures.extend(f"{path}:authenticated:{error}" for error in validate_dashboard_response(authenticated_response, authenticated=True))
                print(f"PROTECTED: path={path} authenticated_status={authenticated_response.status}")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"FINAL: BLOCKED - network_error={type(exc).__name__}")
        return 2
    if failures:
        print("SMOKE FAILURES:")
        for failure in failures:
            print(f"- {failure}")
        print("FINAL: BLOCKED - production smoke contract failed.")
        return 1
    mode = "authenticated+unauthenticated" if username and password else "unauthenticated-only"
    print(f"FINAL: PASS - production smoke contract passed ({mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

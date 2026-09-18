from scripts.production_smoke import (
    PROTECTED_PATHS,
    SmokeResponse,
    validate_dashboard_response,
    validate_health,
)


def test_health_contract_accepts_expected_response() -> None:
    response = SmokeResponse(status=200, headers={"X-Content-Type-Options": "nosniff"}, body=b'{"status":"ok"}')
    assert validate_health(response) == []


def test_health_contract_fails_closed_on_bad_payload() -> None:
    response = SmokeResponse(status=200, headers={"X-Content-Type-Options": "nosniff"}, body=b'{"status":"wrong"}')
    assert "health_payload_invalid" in validate_health(response)


def _dashboard_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "WWW-Authenticate": "Basic",
    }


def test_dashboard_contract_accepts_unauthenticated_401() -> None:
    response = SmokeResponse(status=401, headers=_dashboard_headers(), body=b"")
    assert validate_dashboard_response(response, authenticated=False) == []


def test_dashboard_contract_accepts_authenticated_200() -> None:
    headers = _dashboard_headers()
    headers.pop("WWW-Authenticate")
    response = SmokeResponse(status=200, headers=headers, body=b"ok")
    assert validate_dashboard_response(response, authenticated=True) == []


def test_dashboard_contract_rejects_missing_protection_headers() -> None:
    response = SmokeResponse(status=401, headers={}, body=b"")
    errors = validate_dashboard_response(response, authenticated=False)
    assert "cache_control_not_no_store" in errors
    assert "missing_csp" in errors
    assert "missing_basic_auth_challenge" in errors


def test_production_smoke_covers_current_read_only_workspace_pages() -> None:
    required = {
        "/dashboard/hub",
        "/dashboard",
        "/dashboard/readiness",
        "/dashboard/intelligence-view",
        "/dashboard/verification",
        "/dashboard/quality-coverage",
        "/dashboard/quality-scorecards",
        "/dashboard/indicator-catalog",
        "/dashboard/timeline",
        "/dashboard/changes",
        "/dashboard/search",
        "/dashboard/document",
        "/dashboard/conflicts",
        "/dashboard/provenance",
    }
    assert set(PROTECTED_PATHS) == required

from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.evidence_export as export_api
from app.main import app
from app.services.evidence_export import EXPORT_FIELDS, render_claim_export_csv


client = TestClient(app)


def _enable_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )


def _sample_payload() -> dict[str, object]:
    row = {field: None for field in EXPORT_FIELDS}
    row.update(
        {
            "claim_id": "claim-1",
            "document_id": "doc-1",
            "source_id": "rbi",
            "entity": "Reserve Bank of India",
            "metric": "policy repo rate",
            "canonical_metric": "Policy Repo Rate",
            "indicator_id": "policy_repo_rate",
            "value_text": "5.50%",
            "value_numeric": "5.50",
            "unit": "%",
            "state": "candidate",
            "confidence": 0.95,
            "publication_date": "2026-09-18",
            "temporal_date": "2026-09-18",
            "temporal_basis": "publication_date",
            "quality_gate": "pass",
            "source_url": "https://www.rbi.org.in/example",
            "document_title": 'Statement, "September"',
            "document_source_name": "Reserve Bank of India",
            "document_sha256": "a" * 64,
            "document_content_type": "application/pdf",
            "document_retrieved_at": "2026-09-18T03:00:00+00:00",
            "document_status": "indexed",
            "evidence_excerpt": "The policy repo rate is 5.50 percent.",
        }
    )
    return {
        "generated_at": "2026-09-18T03:00:00+00:00",
        "mode": "read_only_claim_evidence_export",
        "scope": {},
        "summary": {"matching_claims": 1, "returned_claims": 1, "has_more": False},
        "fields": list(EXPORT_FIELDS),
        "rows": [row],
        "safety": {
            "read_only": True,
            "bounded": True,
            "max_rows_per_request": 100,
            "exposes_private_object_keys": False,
        },
    }


def test_export_page_is_private_read_only_surface(monkeypatch) -> None:
    _enable_auth(monkeypatch)

    unauthenticated = client.get("/dashboard/export")
    authenticated = client.get("/dashboard/export", auth=("operator", "secret"))

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.headers["cache-control"] == "no-store"
    assert "Evidence Export" in authenticated.text
    assert "/api/v1/export/claims.json" in authenticated.text
    assert "/api/v1/export/claims.csv" in authenticated.text
    assert "100 rows per request" in authenticated.text
    assert "method=\"post\"" not in authenticated.text.lower()
    assert "/ingest" not in authenticated.text
    assert "trust_promotion_enabled=true" not in authenticated.text.lower()


def test_json_export_reuses_bounded_filters_and_redacts_private_storage(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    captured: dict[str, object] = {}

    def fake_export(**kwargs):
        captured.update(kwargs)
        return _sample_payload()

    monkeypatch.setattr(export_api, "build_claim_export", fake_export)
    response = client.get(
        "/api/v1/export/claims.json?q=repo&source_id=rbi&state=candidate&entity=Reserve&metric=repo&date_from=2026-09-01&date_to=2026-09-18&limit=50&offset=4",
        auth=("operator", "secret"),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"].lower()
    assert response.headers["content-disposition"].endswith('financial-intelligence-claims.json"')
    assert captured["q"] == "repo"
    assert captured["source_id"] == "rbi"
    assert captured["state"] == "candidate"
    assert captured["entity"] == "Reserve"
    assert captured["metric"] == "repo"
    assert str(captured["date_from"]) == "2026-09-01"
    assert str(captured["date_to"]) == "2026-09-18"
    assert captured["limit"] == 50
    assert captured["offset"] == 4
    body = response.text.casefold()
    assert "object_key" not in body
    assert "s3_key" not in body
    assert "secret_access_key" not in body


def test_csv_export_is_well_formed_non_cacheable_and_quoted(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    payload = _sample_payload()
    monkeypatch.setattr(export_api, "build_claim_export", lambda **_kwargs: payload)

    response = client.get("/api/v1/export/claims.csv?limit=1", auth=("operator", "secret"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"].lower()
    assert response.text.splitlines()[0].split(",") == EXPORT_FIELDS
    assert '"Statement, ""September"""' in response.text
    assert "a" * 64 in response.text
    assert "object_key" not in response.text.casefold()


def test_csv_renderer_uses_fixed_field_order() -> None:
    csv_text = render_claim_export_csv(_sample_payload())
    lines = csv_text.splitlines()
    assert lines[0].split(",") == EXPORT_FIELDS
    assert len(lines) == 2


def test_export_query_bounds_and_bad_range_fail_closed(monkeypatch) -> None:
    _enable_auth(monkeypatch)

    assert client.get(
        "/api/v1/export/claims.json?limit=101", auth=("operator", "secret")
    ).status_code == 422
    assert client.get(
        "/api/v1/export/claims.csv?offset=5001", auth=("operator", "secret")
    ).status_code == 422

    def reject_range(**_kwargs):
        raise ValueError("date_from must be on or before date_to")

    monkeypatch.setattr(export_api, "build_claim_export", reject_range)
    invalid = client.get(
        "/api/v1/export/claims.json?date_from=2026-09-18&date_to=2026-09-01",
        auth=("operator", "secret"),
    )
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert "date_from must be on or before date_to" in invalid.json()["detail"]


def test_export_openapi_contract_has_no_write_methods() -> None:
    paths = {
        path: operations
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1/export")
    }
    assert paths
    for operations in paths.values():
        methods = {method.lower() for method in operations}
        assert not ({"post", "put", "patch", "delete"} & methods)
        assert methods <= {"get", "head", "options"}

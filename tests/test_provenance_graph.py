from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.provenance_graph_dashboard as graph_api
import app.services.provenance_graph as graph_service
from app.main import app


client = TestClient(app)


def _detail() -> dict[str, object]:
    return {
        "document": {
            "document_id": "doc-1",
            "source_id": "rbi",
            "source_name": "Reserve Bank of India",
            "source_url": "https://www.rbi.org.in/source",
            "final_url": "https://www.rbi.org.in/document.pdf",
            "title": "Policy Decision",
            "content_type": "application/pdf",
            "sha256": "a" * 64,
            "retrieved_at": "2026-09-18T01:00:00+00:00",
            "chunk_count": 2,
            "status": "indexed",
            "raw_evidence_retained": True,
            "object_reference_redacted": True,
        },
        "discoveries": [
            {
                "monitor_id": "rbi-press-releases-rss",
                "source_id": "rbi",
                "url": "https://www.rbi.org.in/document.pdf",
                "title": "Policy Decision",
                "publication_date": "2026-09-18",
                "status": "ingested",
                "first_seen_at": "2026-09-18T00:50:00+00:00",
                "last_seen_at": "2026-09-18T00:50:00+00:00",
                "seen_count": 1,
                "attempt_count": 1,
                "last_error_code": None,
            }
        ],
        "claims": [
            {
                "claim_id": "claim-1",
                "entity": "Reserve Bank of India",
                "metric": "Repo Rate",
                "canonical_metric": "Policy Repo Rate",
                "indicator_id": "policy_repo_rate",
                "normalization_basis": "exact_catalog_alias",
                "value_text": "5.50%",
                "value_numeric": "5.50",
                "unit": "%",
                "publication_date": "2026-09-18",
                "effective_date": None,
                "state": "candidate",
                "confidence": 0.98,
                "source_url": "https://www.rbi.org.in/document.pdf",
                "evidence_chunk_index": 1,
                "evidence_text": "The repo rate is 5.50 per cent.",
                "quality_gate": "pass",
                "quality_rejection_reason": None,
                "created_at": "2026-09-18T01:01:00+00:00",
                "updated_at": "2026-09-18T01:01:00+00:00",
                "attribution": {
                    "canonical_entity": "Reserve Bank of India",
                    "source_default_entity": "Reserve Bank of India",
                    "basis": "source_default",
                    "matched_aliases": [],
                    "ambiguous_candidates": [],
                    "evidence_text": "The repo rate is 5.50 per cent.",
                    "created_at": "2026-09-18T01:01:00+00:00",
                },
                "verification_events": [
                    {
                        "from_state": "candidate",
                        "to_state": "candidate",
                        "reason": "insufficient_independent_sources",
                        "supporting_source_ids": ["rbi"],
                        "conflicting_source_ids": [],
                        "created_at": "2026-09-18T01:02:00+00:00",
                    }
                ],
                "trust_events": [],
                "superseded_by": None,
                "supersedes": [],
            }
        ],
    }


def test_graph_builds_source_document_claim_and_audit_lineage(monkeypatch) -> None:
    monkeypatch.setattr(graph_service, "build_document_detail", lambda _document_id: _detail())
    result = graph_service.build_provenance_graph("doc-1")

    assert result is not None
    assert result["document_id"] == "doc-1"
    node_types = result["summary"]["node_type_counts"]
    assert node_types["source"] == 1
    assert node_types["document"] == 1
    assert node_types["claim"] == 1
    assert node_types["discovery"] == 1
    assert node_types["entity_attribution"] == 1
    assert node_types["verification_event"] == 1
    edge_types = {edge["type"] for edge in result["edges"]}
    assert {"published_evidence", "discovered_document", "extracted_claim", "attributed_as", "verification_event"}.issubset(edge_types)
    document_node = next(node for node in result["nodes"] if node["type"] == "document")
    assert document_node["metadata"]["sha256"] == "a" * 64
    assert "object_key" not in document_node["metadata"]
    assert result["safety"]["exposes_object_keys"] is False
    assert result["safety"]["mutates_data"] is False


def test_graph_returns_none_when_document_detail_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(graph_service, "build_document_detail", lambda _document_id: None)
    assert graph_service.build_provenance_graph("missing") is None


def test_provenance_routes_are_private_and_read_only(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type("Settings", (), {"dashboard_username": "operator", "dashboard_password": "secret"})(),
    )
    monkeypatch.setattr(
        graph_api,
        "build_provenance_graph",
        lambda document_id: {
            "generated_at": "2026-09-18T02:00:00+00:00",
            "mode": "read_only_provenance_graph",
            "document_id": document_id,
            "summary": {"nodes": 2, "edges": 1, "node_type_counts": {"source": 1, "document": 1}},
            "nodes": [],
            "edges": [],
            "safety": {"note": "read-only", "exposes_object_keys": False},
        },
    )

    assert client.get("/dashboard/provenance").status_code == 401
    page = client.get("/dashboard/provenance", auth=("operator", "secret"))
    status_response = client.get(
        "/dashboard/provenance/doc-1/status",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Provenance Graph" in page.text
    lowered = page.text.lower()
    assert "/ingest" not in lowered
    assert "method=\"post\"" not in lowered
    assert status_response.status_code == 200
    assert status_response.headers["cache-control"] == "no-store"
    assert status_response.json()["document_id"] == "doc-1"

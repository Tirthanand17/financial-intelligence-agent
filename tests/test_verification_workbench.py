from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.verification_dashboard as verification_api
import app.services.verification_workbench as workbench
from app.main import app
from app.storage.database import (
    Base,
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimSupersessionRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
)


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _claim(
    claim_id: str,
    *,
    source_id: str,
    entity: str,
    metric: str,
    value: str,
    numeric: str,
    state: str,
    publication_date: date,
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id=source_id,
        source_url=f"https://example.test/{claim_id}",
        entity=entity,
        metric=metric,
        value_text=value,
        value_numeric=Decimal(numeric),
        unit="%",
        publication_date=publication_date,
        effective_date=None,
        evidence_text=f"Official evidence for {metric}: {value}",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
        created_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
    )


def _attribution(
    claim_id: str,
    *,
    canonical_entity: str,
    source_default: str,
    basis: str,
) -> ClaimEntityAttributionRecord:
    return ClaimEntityAttributionRecord(
        claim_id=claim_id,
        canonical_entity=canonical_entity,
        source_default_entity=source_default,
        basis=basis,
        matched_aliases="[]",
        ambiguous_candidates="[]",
        evidence_text="auditable attribution",
        created_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
    )


def test_workbench_explains_verification_and_trust_without_mutation(monkeypatch) -> None:
    Session = _session_factory()
    entity = "Reserve Bank of India"
    day = date(2026, 9, 17)

    with Session() as session:
        session.add_all(
            [
                _claim(
                    "claim-rbi",
                    source_id="rbi",
                    entity=entity,
                    metric="Policy Repo Rate",
                    value="5.50%",
                    numeric="5.50",
                    state="verified",
                    publication_date=day,
                ),
                _claim(
                    "claim-sebi",
                    source_id="sebi",
                    entity=entity,
                    metric="Policy Repo Rate",
                    value="5.50%",
                    numeric="5.50",
                    state="verified",
                    publication_date=day,
                ),
                _claim(
                    "claim-nse",
                    source_id="nse",
                    entity="National Stock Exchange of India",
                    metric="Standalone Metric",
                    value="2.00%",
                    numeric="2.00",
                    state="candidate",
                    publication_date=day,
                ),
                _attribution(
                    "claim-rbi",
                    canonical_entity=entity,
                    source_default="Reserve Bank of India",
                    basis="source_default",
                ),
                _attribution(
                    "claim-sebi",
                    canonical_entity=entity,
                    source_default="Securities and Exchange Board of India",
                    basis="explicit_local_alias",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(workbench, "get_session", lambda: Session())
    result = workbench.build_verification_workbench(limit=20)

    by_id = {item["claim_id"]: item for item in result["items"]}
    rbi = by_id["claim-rbi"]
    nse = by_id["claim-nse"]

    assert rbi["verification_reason"] == "independent_sources_agree"
    assert rbi["supporting_independence_groups"] == ["rbi", "sebi"]
    assert rbi["trust_diagnostic"]["policy_eligible_without_mutation"] is True
    assert rbi["trust_diagnostic"]["reason"] == (
        "verified_primary_with_independent_authoritative_corroboration"
    )
    assert nse["verification_reason"] == "insufficient_independent_sources"
    assert result["summary"]["actionable_review_items"] == 1
    assert result["summary"]["trust_policy_eligible"] == 1
    assert result["safety"]["mutates_claim_state"] is False
    assert result["safety"]["creates_trust_events"] is False

    with Session() as session:
        states = {row.id: row.state for row in session.scalars(select(ClaimRecord))}
        assert states == {
            "claim-rbi": "verified",
            "claim-sebi": "verified",
            "claim-nse": "candidate",
        }
        assert list(session.scalars(select(ClaimTrustEventRecord))) == []


def test_workbench_surfaces_audit_and_supersession_history_with_filters(monkeypatch) -> None:
    Session = _session_factory()
    old_day = date(2026, 8, 1)
    new_day = date(2026, 9, 1)

    with Session() as session:
        session.add_all(
            [
                _claim(
                    "old-rbi",
                    source_id="rbi",
                    entity="Reserve Bank of India",
                    metric="Cash Reserve Ratio",
                    value="4.00%",
                    numeric="4.00",
                    state="superseded",
                    publication_date=old_day,
                ),
                _claim(
                    "new-rbi",
                    source_id="rbi",
                    entity="Reserve Bank of India",
                    metric="Cash Reserve Ratio",
                    value="4.50%",
                    numeric="4.50",
                    state="candidate",
                    publication_date=new_day,
                ),
                ClaimVerificationEventRecord(
                    id="verify-event",
                    claim_id="old-rbi",
                    from_state="candidate",
                    to_state="verified",
                    reason="independent_sources_agree",
                    supporting_source_ids='["rbi", "sebi"]',
                    conflicting_source_ids="[]",
                    created_at=datetime(2026, 8, 2, 5, 0, tzinfo=UTC),
                ),
                ClaimTrustEventRecord(
                    id="trust-event",
                    claim_id="old-rbi",
                    from_state="verified",
                    to_state="trusted",
                    reason="verified_primary_with_independent_authoritative_corroboration",
                    corroborating_source_ids='["sebi"]',
                    created_at=datetime(2026, 8, 3, 5, 0, tzinfo=UTC),
                ),
                ClaimSupersessionRecord(
                    older_claim_id="old-rbi",
                    newer_claim_id="new-rbi",
                    newer_document_id="doc-new-rbi",
                    temporal_kind="publication",
                    older_date=old_day,
                    newer_date=new_day,
                    created_at=datetime(2026, 9, 1, 5, 0, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(workbench, "get_session", lambda: Session())
    result = workbench.build_verification_workbench(
        source_id="rbi",
        state="superseded",
        limit=10,
    )

    assert result["scope"] == {"source_id": "rbi", "state": "superseded", "limit": 10}
    assert result["summary"]["total_claims_in_scope"] == 1
    assert result["summary"]["verification_events_in_scope"] == 1
    assert result["summary"]["trust_events_in_scope"] == 1
    item = result["items"][0]
    assert item["claim_id"] == "old-rbi"
    assert item["latest_verification_event"]["supporting_source_ids"] == ["rbi", "sebi"]
    assert item["latest_trust_event"]["corroborating_source_ids"] == ["sebi"]
    assert item["supersession"]["superseded_by_claim_id"] == "new-rbi"
    assert item["supersession"]["newer_date"] == "2026-09-01"


def test_verification_routes_reuse_dashboard_auth_and_stay_read_only(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )
    monkeypatch.setattr(
        verification_api,
        "build_verification_workbench",
        lambda **kwargs: {
            "generated_at": "2026-09-17T06:00:00+00:00",
            "scope": kwargs,
            "summary": {"total_claims_in_scope": 1},
            "available_sources": [],
            "reason_counts": {},
            "items": [],
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/verification").status_code == 401
    page = client.get("/dashboard/verification", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/verification/status?source_id=rbi&state=candidate&limit=20",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Claim Verification Workbench" in page.text
    assert "Read-only" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert "trust_promotion_enabled=true" not in page.text.lower()

    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["scope"] == {
        "source_id": "rbi",
        "state": "candidate",
        "limit": 20,
    }

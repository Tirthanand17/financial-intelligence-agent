from __future__ import annotations

from app.recovery.rehearsal import build_recovery_rehearsal


def _readiness(*, safe: bool = True) -> dict[str, object]:
    return {
        "safe": safe,
        "counts": {"documents": 2, "claims": 3},
        "claim_states": {"candidate": 3},
        "monitor_states": {"ready": 4},
        "evidence_integrity": {"safe": safe, "verified": 2 if safe else 1, "expected": 2},
        "qdrant_reconciliation": {
            "safe": safe,
            "expected_points": 5,
            "actual_points": 5 if safe else 4,
        },
    }


def _documents() -> list[dict[str, object]]:
    return [
        {
            "document_id": "a",
            "source_id": "rbi",
            "sha256": "a" * 64,
            "content_type": "application/pdf",
            "chunk_count": 2,
            "retrieved_at": "2026-09-18T00:00:00+00:00",
            "status": "indexed",
        },
        {
            "document_id": "b",
            "source_id": "sebi",
            "sha256": "b" * 64,
            "content_type": "application/pdf",
            "chunk_count": 3,
            "retrieved_at": "2026-09-18T00:01:00+00:00",
            "status": "indexed",
        },
    ]


def test_recovery_rehearsal_is_ready_only_when_all_read_only_invariants_match() -> None:
    report = build_recovery_rehearsal(
        readiness_loader=lambda: _readiness(safe=True),
        document_loader=_documents,
    )

    assert report["rehearsal_ready"] is True
    assert all(report["checks"].values())
    assert len(report["manifest_sha256"]) == 64
    assert report["execution_boundary"]["isolated_restore_executed"] is False
    assert report["execution_boundary"]["production_mutated"] is False
    assert report["execution_boundary"]["requires_explicit_operator_approval_for_real_restore"] is True
    serialized = str(report).casefold()
    assert "object_key" not in serialized
    assert "secret_access_key" not in serialized


def test_recovery_rehearsal_fails_closed_on_readiness_mismatch() -> None:
    report = build_recovery_rehearsal(
        readiness_loader=lambda: _readiness(safe=False),
        document_loader=_documents,
    )
    assert report["rehearsal_ready"] is False
    assert report["checks"]["recovery_readiness_safe"] is False
    assert report["checks"]["all_evidence_hashes_verified"] is False
    assert report["checks"]["qdrant_reconciled"] is False


def test_recovery_rehearsal_fails_closed_when_manifest_count_or_chunks_drift() -> None:
    readiness = _readiness(safe=True)
    readiness["counts"] = {"documents": 3, "claims": 3}
    readiness["qdrant_reconciliation"] = {"safe": True, "expected_points": 6, "actual_points": 6}
    report = build_recovery_rehearsal(
        readiness_loader=lambda: readiness,
        document_loader=_documents,
    )
    assert report["rehearsal_ready"] is False
    assert report["checks"]["document_manifest_count_matches_database"] is False
    assert report["checks"]["document_chunk_total_matches_qdrant_expectation"] is False


def test_manifest_digest_is_deterministic_for_same_inventory() -> None:
    first = build_recovery_rehearsal(
        readiness_loader=lambda: _readiness(safe=True),
        document_loader=_documents,
    )
    second = build_recovery_rehearsal(
        readiness_loader=lambda: _readiness(safe=True),
        document_loader=_documents,
    )
    assert first["manifest_sha256"] == second["manifest_sha256"]

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select

from app.recovery.readiness import build_recovery_readiness_report
from app.storage.database import DocumentRecord, get_session


def _document_manifest() -> list[dict[str, object]]:
    """Return a secret-free reconstruction inventory without object-store keys."""
    with get_session() as session:
        documents = list(session.scalars(select(DocumentRecord)))

    rows = [
        {
            "document_id": row.id,
            "source_id": row.source_id,
            "sha256": row.sha256,
            "content_type": row.content_type,
            "chunk_count": int(row.chunk_count),
            "retrieved_at": row.retrieved_at.astimezone(UTC).isoformat(),
            "status": row.status,
        }
        for row in documents
    ]
    rows.sort(key=lambda item: (str(item["source_id"]), str(item["document_id"])))
    return rows


def _manifest_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_recovery_rehearsal(
    *,
    readiness_loader: Callable[[], dict[str, object]] = build_recovery_readiness_report,
    document_loader: Callable[[], list[dict[str, object]]] = _document_manifest,
) -> dict[str, object]:
    """Build a non-destructive restore rehearsal manifest from live preserved evidence.

    This verifies whether an isolated restore *could* be attempted from the current
    reconciled state. It never creates a backup, provisions a target, writes cloud
    data, rewrites evidence, or claims that an isolated restore has occurred.
    """
    readiness = readiness_loader()
    documents = document_loader()
    counts = readiness.get("counts", {})
    evidence = readiness.get("evidence_integrity", {})
    qdrant = readiness.get("qdrant_reconciliation", {})

    declared_documents = int(counts.get("documents", -1))
    manifest_count_matches = declared_documents == len(documents)
    chunk_total = sum(int(row["chunk_count"]) for row in documents)
    qdrant_expected = qdrant.get("expected_points")
    chunk_total_matches_qdrant_expectation = (
        qdrant_expected is not None and int(qdrant_expected) == chunk_total
    )

    checks = {
        "recovery_readiness_safe": bool(readiness.get("safe")),
        "all_evidence_hashes_verified": bool(evidence.get("safe")),
        "qdrant_reconciled": bool(qdrant.get("safe")),
        "document_manifest_count_matches_database": manifest_count_matches,
        "document_chunk_total_matches_qdrant_expectation": chunk_total_matches_qdrant_expectation,
        "manifest_contains_no_object_keys": all("object_key" not in row for row in documents),
    }
    rehearsal_ready = all(checks.values())

    immutable = {
        "counts": counts,
        "claim_states": readiness.get("claim_states", {}),
        "monitor_states": readiness.get("monitor_states", {}),
        "evidence_integrity": evidence,
        "qdrant_reconciliation": qdrant,
        "documents": documents,
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_recovery_rehearsal_manifest",
        "rehearsal_ready": rehearsal_ready,
        "checks": checks,
        "manifest_sha256": _manifest_digest(immutable),
        "manifest": immutable,
        "restore_sequence": [
            "Provision isolated PostgreSQL, object-store, and Qdrant targets only after explicit operator approval.",
            "Restore database metadata/history into the isolated database and validate modeled schema/migration head.",
            "Restore exact raw evidence bytes and re-check every document SHA-256 against this manifest.",
            "Rebuild or restore Qdrant points from preserved document chunks and require exact expected-point reconciliation.",
            "Run claim, attribution, supersession, verification, trust-event, monitor, and queue integrity checks.",
            "Keep the isolated environment disconnected from production write paths until every check passes.",
        ],
        "execution_boundary": {
            "provider_backup_created": False,
            "isolated_targets_provisioned": False,
            "isolated_restore_executed": False,
            "production_mutated": False,
            "requires_explicit_operator_approval_for_real_restore": True,
            "note": (
                "This is the maximum non-destructive rehearsal available against current live stores. "
                "A real restore drill requires separate isolated targets and must not reuse production destinations."
            ),
        },
    }

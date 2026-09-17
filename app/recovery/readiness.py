from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import func, select

from app.core.config import get_settings
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimSupersessionRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
    get_session,
)
from app.storage.object_store import get_raw_document
from app.storage.vector_store import get_qdrant_client


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def verify_preserved_evidence(
    documents: list[DocumentRecord],
    *,
    loader: Callable[[str], bytes] = get_raw_document,
) -> dict[str, object]:
    """Verify exact preserved bytes without mutating remote storage."""
    verified = 0
    missing_or_unreadable: list[str] = []
    hash_mismatches: list[str] = []

    for document in documents:
        try:
            content = loader(document.object_key)
        except Exception:
            # Do not expose provider error details or credentials in readiness output.
            missing_or_unreadable.append(document.id)
            continue

        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_sha != document.sha256:
            hash_mismatches.append(document.id)
            continue
        verified += 1

    return {
        "verified": verified,
        "expected": len(documents),
        "missing_or_unreadable_document_ids": sorted(missing_or_unreadable),
        "hash_mismatch_document_ids": sorted(hash_mismatches),
        "safe": verified == len(documents) and not missing_or_unreadable and not hash_mismatches,
    }


def qdrant_reconciliation(expected_points: int) -> dict[str, object]:
    settings = get_settings()
    client = get_qdrant_client()
    try:
        if not client.collection_exists(settings.qdrant_collection):
            actual = 0
        else:
            actual = int(
                client.count(
                    collection_name=settings.qdrant_collection,
                    exact=True,
                ).count
            )
    except Exception:
        return {
            "expected_points": expected_points,
            "actual_points": None,
            "safe": False,
            "status": "unavailable",
        }

    return {
        "expected_points": expected_points,
        "actual_points": actual,
        "safe": actual == expected_points,
        "status": "matched" if actual == expected_points else "mismatch",
    }


def build_recovery_readiness_report() -> dict[str, object]:
    """Build a secret-free, read-only recovery inventory for the live stores.

    This is not a provider backup and never changes database, object-store, or
    vector-store state. It verifies that the three stores agree closely enough
    to make a later isolated restore test meaningful.
    """
    with get_session() as session:
        documents = list(session.scalars(select(DocumentRecord)))
        claims = list(session.scalars(select(ClaimRecord)))
        monitor_states = list(session.scalars(select(SourceMonitorStateRecord)))

        counts = {
            "documents": len(documents),
            "claims": len(claims),
            "claim_entity_attributions": _count(session, ClaimEntityAttributionRecord),
            "claim_supersessions": _count(session, ClaimSupersessionRecord),
            "claim_verification_events": _count(session, ClaimVerificationEventRecord),
            "claim_trust_events": _count(session, ClaimTrustEventRecord),
            "source_monitor_states": len(monitor_states),
            "source_monitor_runs": _count(session, SourceMonitorRunRecord),
            "source_monitor_discoveries": _count(session, SourceMonitorDiscoveryRecord),
        }

    evidence = verify_preserved_evidence(documents)
    expected_qdrant = sum(int(document.chunk_count) for document in documents)
    qdrant = qdrant_reconciliation(expected_qdrant)

    claim_states = Counter(str(claim.state) for claim in claims)
    monitor_state_counts = Counter(str(row.state) for row in monitor_states)

    safe = bool(evidence["safe"]) and bool(qdrant["safe"])

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_recovery_readiness",
        "safe": safe,
        "counts": counts,
        "claim_states": dict(sorted(claim_states.items())),
        "monitor_states": dict(sorted(monitor_state_counts.items())),
        "evidence_integrity": evidence,
        "qdrant_reconciliation": qdrant,
        "recovery_boundary": {
            "provider_backup_created": False,
            "isolated_restore_executed": False,
            "note": (
                "This report validates recovery readiness only. A real provider backup and "
                "isolated restore test remain separate operator-approved steps."
            ),
        },
    }

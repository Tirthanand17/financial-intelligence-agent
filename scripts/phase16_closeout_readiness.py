import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.claims.trust_storage import assess_persisted_trust
from app.core.config import get_settings
from app.storage.database import (
    ClaimRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
    get_session,
)


def main() -> None:
    settings = get_settings()
    print("PHASE 16 CLAIM QUALITY / VERIFICATION CLOSEOUT - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    blockers: list[str] = []
    if settings.source_monitoring_enabled:
        blockers.append("gate:source_monitoring_enabled")
    if settings.source_auto_ingest_enabled:
        blockers.append("gate:source_auto_ingest_enabled")
    if settings.trust_promotion_enabled:
        blockers.append("gate:trust_promotion_enabled")

    with get_session() as session:
        records = list(
            session.scalars(
                select(ClaimRecord)
                .where(
                    ClaimRecord.state.notin_(
                        [ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value]
                    )
                )
                .order_by(ClaimRecord.source_id, ClaimRecord.metric, ClaimRecord.id)
            )
        )
        states = Counter(record.state for record in records)
        quality_reasons: Counter[str] = Counter()
        unsafe_high_state: list[str] = []
        promotable: list[str] = []

        for record in records:
            reason = claim_quality_rejection_reason(record.metric, record.evidence_text)
            if reason is not None:
                quality_reasons[reason] += 1
                if record.state in {
                    ClaimState.VERIFIED.value,
                    ClaimState.TRUSTED.value,
                }:
                    unsafe_high_state.append(record.id)
                continue

            if record.state == ClaimState.VERIFIED.value:
                decision = assess_persisted_trust(session, record)
                if decision.state is ClaimState.TRUSTED:
                    promotable.append(record.id)

        trust_events = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        ) or 0
        verification_events = session.scalar(
            select(func.count()).select_from(ClaimVerificationEventRecord)
        ) or 0

    quality_issue_count = sum(quality_reasons.values())
    print(f"ACTIVE CLAIMS REVIEWED: {len(records)}")
    print("STATE COUNTS: " + (", ".join(f"{k}={v}" for k, v in sorted(states.items())) or "-"))
    print(f"LEGACY QUALITY ISSUES: {quality_issue_count}")
    for reason, count in sorted(quality_reasons.items()):
        print(f"QUALITY {reason}: count={count}")
    print(f"QUALITY-FAILED VERIFIED/TRUSTED: {len(unsafe_high_state)}")
    print(f"UNREVIEWED PROMOTABLE CLAIMS: {len(promotable)}")
    print(f"VERIFICATION EVENTS TOTAL: {verification_events}")
    print(f"TRUST EVENTS TOTAL: {trust_events}")

    if unsafe_high_state:
        blockers.append("quality:failed_claim_has_high_state")
    if promotable:
        blockers.append("trust:real_promotion_candidate_requires_controlled_review")
    if trust_events:
        blockers.append("trust:promotion_event_exists_while_gate_expected_off")

    if blockers:
        print(
            "FINAL: BLOCKED - Phase 16 closeout invariants are not satisfied. "
            f"blockers={','.join(dict.fromkeys(blockers))}"
        )
        return

    print(
        "FINAL: PASS-READ-ONLY - future structured claims are protected by the "
        "quality floor, legacy quality debt remains preserved only below verified/trusted "
        "state, no unreviewed real trust candidate exists, and trust promotion remains off."
    )


if __name__ == "__main__":
    main()

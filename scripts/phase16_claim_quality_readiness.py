import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.core.config import get_settings
from app.storage.database import ClaimRecord, get_session


EXAMPLE_LIMIT = 3


def main() -> None:
    settings = get_settings()
    print("PHASE 16 CLAIM QUALITY / VERIFICATION READINESS - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    if settings.source_monitoring_enabled or settings.source_auto_ingest_enabled:
        print("FINAL: BLOCKED - normal monitoring and auto-ingestion must remain off for this audit.")
        return
    if settings.trust_promotion_enabled:
        print("FINAL: BLOCKED - trust promotion must remain disabled during quality hardening.")
        return

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

    reasons: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    states: Counter[str] = Counter(record.state for record in records)
    for record in records:
        reason = claim_quality_rejection_reason(record.metric, record.evidence_text)
        if reason is None:
            continue
        reasons[reason] += 1
        bucket = examples.setdefault(reason, [])
        if len(bucket) < EXAMPLE_LIMIT:
            bucket.append(f"{record.source_id}:{record.metric}={record.value_text}")

    quality_issue_count = sum(reasons.values())
    print(f"ACTIVE CLAIMS REVIEWED: {len(records)}")
    print("STATE COUNTS: " + (", ".join(f"{k}={v}" for k, v in sorted(states.items())) or "-"))
    print(f"LEGACY QUALITY ISSUES: {quality_issue_count}")
    for reason, count in sorted(reasons.items()):
        print(f"QUALITY {reason}: count={count} examples={' | '.join(examples[reason])}")

    verified_or_trusted = states[ClaimState.VERIFIED.value] + states[ClaimState.TRUSTED.value]
    print(f"VERIFIED_OR_TRUSTED CLAIMS: {verified_or_trusted}")
    print(
        "FINAL: PASS-READ-ONLY - claim-quality debt was inventoried without changing "
        "claim states or evidence. The new eligibility floor applies only to future "
        "derived candidates; legacy rows remain preserved for explicit review."
    )


if __name__ == "__main__":
    main()

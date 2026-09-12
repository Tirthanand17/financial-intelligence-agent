import argparse
import sys
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.claims.models import ClaimState
from app.claims.trust_storage import assess_persisted_trust
from app.storage.database import ClaimRecord, get_session


def _scope(record: ClaimRecord) -> str:
    if record.effective_date is not None:
        return f"effective:{record.effective_date.isoformat()}"
    if record.publication_date is not None:
        return f"publication:{record.publication_date.isoformat()}"
    return "undated"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Phase 4 report showing whether persisted claims would "
            "qualify for TRUSTED under the current policy. No states are changed."
        )
    )
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--metric", default=None)
    args = parser.parse_args()

    with get_session() as session:
        statement = select(ClaimRecord).where(
            ClaimRecord.state.notin_(
                [ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value]
            )
        )
        if args.source_id:
            statement = statement.where(ClaimRecord.source_id == args.source_id)
        if args.metric:
            statement = statement.where(ClaimRecord.metric == args.metric)

        records = list(
            session.scalars(
                statement.order_by(
                    ClaimRecord.entity,
                    ClaimRecord.metric,
                    ClaimRecord.source_id,
                )
            )
        )

        print("TRUST READINESS REPORT - READ ONLY")
        print(f"ACTIVE CLAIMS REVIEWED: {len(records)}")

        promotable = 0
        for record in records:
            decision = assess_persisted_trust(session, record)
            if (
                record.state != ClaimState.TRUSTED.value
                and decision.state is ClaimState.TRUSTED
            ):
                promotable += 1

            corroboration = ",".join(decision.corroborating_source_ids) or "-"
            print(
                f"{record.source_id} | {record.entity} | {record.metric} = "
                f"{record.value_text} | scope={_scope(record)} | "
                f"current={record.state} | decision={decision.state.value} | "
                f"reason={decision.reason} | corroboration={corroboration}"
            )

        print(f"PROMOTABLE UNDER CURRENT POLICY: {promotable}")
        print("FINAL: READ-ONLY - no claim states or audit rows were changed.")


if __name__ == "__main__":
    main()

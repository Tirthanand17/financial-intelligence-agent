from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import select

# Allow `python scripts/validate_ddnews_repo_rate.py` from a repository checkout
# without requiring callers to set PYTHONPATH manually.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.ingestion import ingest_url
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    get_session,
)


DDNEWS_URL = (
    "https://ddnews.gov.in/en/"
    "rbi-keeps-repo-rate-unchanged-at-5-25-retains-neutral-stance-amid-global-uncertainties/"
)


def main() -> None:
    """Validate one real dated DD News corroborating document end to end.

    This intentionally performs normal trusted-source ingestion, so accepted raw
    evidence is preserved in B2, document provenance/claims are stored in
    PostgreSQL, and chunks are indexed in Qdrant. Re-running is safe because the
    existing ingestion path is content/idempotency aware.

    The script does NOT promote any claim to TRUSTED.
    """
    result = ingest_url("ddnews", DDNEWS_URL)
    document_id = str(result["document_id"])

    with get_session() as session:
        claims = list(
            session.scalars(
                select(ClaimRecord).where(
                    ClaimRecord.document_id == document_id,
                    ClaimRecord.source_id == "ddnews",
                    ClaimRecord.metric == "Policy Repo Rate",
                )
            )
        )

        print(f"INGEST STATUS: {result['status']}")
        print(f"DOCUMENT: {document_id}")
        print(f"REPO-RATE CLAIMS: {len(claims)}")

        if not claims:
            raise SystemExit("FINAL: FAIL - no DD News Policy Repo Rate claim found")

        valid = []
        for claim in claims:
            attribution = session.scalar(
                select(ClaimEntityAttributionRecord).where(
                    ClaimEntityAttributionRecord.claim_id == claim.id
                )
            )
            basis = attribution.basis if attribution is not None else None

            print(
                f"{claim.entity} | {claim.metric} = {claim.value_text} | "
                f"numeric={claim.value_numeric} | unit={claim.unit} | "
                f"publication_date={claim.publication_date} | state={claim.state} | "
                f"attribution={basis}"
            )

            if (
                claim.entity == "Reserve Bank of India"
                and claim.value_numeric == Decimal("5.25")
                and claim.unit == "%"
                and claim.publication_date is not None
                and claim.publication_date.isoformat() == "2026-06-05"
                and basis == "explicit_local_alias"
            ):
                valid.append(claim)

        if len(valid) != 1:
            raise SystemExit(
                "FINAL: FAIL - expected exactly one dated, explicitly attributed "
                "RBI repo-rate claim at 5.25%"
            )

    print(
        "FINAL: PASS - real DD News evidence is preserved and yields one dated, "
        "explicitly attributed RBI Policy Repo Rate 5.25% claim."
    )
    print("TRUST PROMOTION: NOT RUN")


if __name__ == "__main__":
    main()

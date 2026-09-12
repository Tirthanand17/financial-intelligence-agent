from decimal import Decimal
from pathlib import Path
import sys

import httpx
from sqlalchemy import select

# Allow direct execution from a repository checkout without requiring PYTHONPATH.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.ingestion import ingest_url
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    get_session,
)


RBI_MPC_JUNE_2026_URL = (
    "https://rbidocs.rbi.org.in/rdocs/PressRelease/PDFs/"
    "PR3855508EB4A59FF46F9B57BBA200AA250B8.PDF"
)


def main() -> None:
    """Validate dated primary RBI evidence without weakening source controls.

    The URL is the RBI-hosted Monetary Policy Statement / MPC resolution for
    June 3-5, 2026. Normal ingestion rules apply: allow-listed host validation,
    bounded retries, challenge-page rejection, B2 preservation, PostgreSQL
    provenance/claims, and Qdrant indexing.

    If RBI's web application firewall returns a challenge/rejection page, this
    script reports the block and stops. It never changes headers or controls to
    bypass anti-bot protection and never promotes a claim to TRUSTED.
    """
    try:
        result = ingest_url("rbi", RBI_MPC_JUNE_2026_URL)
    except (ConnectionError, ValueError, httpx.HTTPError) as exc:
        raise SystemExit(
            "FINAL: BLOCKED - official RBI evidence could not be retrieved safely. "
            f"No trust promotion was attempted. Reason: {exc}"
        ) from exc

    document_id = str(result["document_id"])

    with get_session() as session:
        claims = list(
            session.scalars(
                select(ClaimRecord).where(
                    ClaimRecord.document_id == document_id,
                    ClaimRecord.source_id == "rbi",
                    ClaimRecord.entity == "Reserve Bank of India",
                    ClaimRecord.metric == "Policy Repo Rate",
                )
            )
        )

        print(f"INGEST STATUS: {result['status']}")
        print(f"DOCUMENT: {document_id}")
        print(f"RBI REPO-RATE CLAIMS: {len(claims)}")

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
                claim.value_numeric == Decimal("5.25")
                and claim.unit == "%"
                and claim.publication_date is not None
                and claim.publication_date.isoformat() == "2026-06-05"
                and basis in {"source_default", "explicit_local_alias"}
            ):
                valid.append(claim)

        if not valid:
            raise SystemExit(
                "FINAL: FAIL - RBI evidence was retrieved, but no dated primary "
                "Policy Repo Rate 5.25% claim was derived."
            )

        verified = [claim for claim in valid if claim.state == "verified"]
        print(f"VALID PRIMARY CLAIMS: {len(valid)}")
        print(f"VERIFIED PRIMARY CLAIMS: {len(verified)}")

    print(
        "FINAL: PASS - dated primary RBI Policy Repo Rate 5.25% evidence is "
        "preserved and structurally valid."
    )
    print("TRUST PROMOTION: NOT RUN")


if __name__ == "__main__":
    main()

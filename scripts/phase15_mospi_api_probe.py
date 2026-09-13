import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.sources.mospi import (
    MOSPI_LATEST_RELEASES_API_URL,
    discover_mospi_latest_releases,
    download_mospi_latest_releases,
)

SOURCE_ID = "mospi"
DISCOVERY_LIMIT = 10


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 15 read-only live probe for the official MoSPI latest-releases API. "
            "The API response may be fetched once; discovered PDFs are not downloaded."
        )
    )
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    print("PHASE 15 MOSPI LATEST-RELEASES API PROBE - READ ONLY")
    print(f"SOURCE: {SOURCE_ID}")
    print(f"ENDPOINT: {MOSPI_LATEST_RELEASES_API_URL}")
    print(f"DISCOVERY LIMIT: {DISCOVERY_LIMIT}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    if (
        settings.source_monitoring_enabled
        or settings.source_auto_ingest_enabled
        or settings.trust_promotion_enabled
    ):
        print("FINAL: BLOCKED - all global monitoring/auto-ingest/trust gates must remain false.")
        return
    if not args.allow_network:
        print("FINAL: BLOCKED - --allow-network is required for the one read-only API request.")
        return

    try:
        downloaded = download_mospi_latest_releases(SOURCE_ID, MOSPI_LATEST_RELEASES_API_URL)
        discovery = discover_mospi_latest_releases(
            downloaded.content,
            limit=DISCOVERY_LIMIT,
        )
    except ConnectionError:
        print("FINAL: BLOCKED - MoSPI API request failed with transient_network_error; no writes occurred.")
        return
    except Exception as exc:
        print(
            "FINAL: BLOCKED - MoSPI API failed trusted-source or response validation; "
            f"no writes occurred. error_type={type(exc).__name__}"
        )
        return

    print(
        "API RESULT: "
        f"content_type={downloaded.content_type} bytes={len(downloaded.content)}"
    )
    print(
        "DISCOVERY RESULT: "
        f"discovered={len(discovery.items)} rejected={discovery.rejected_count} "
        f"rejection_reasons={dict(discovery.rejection_reasons) or '-'}"
    )
    for index, item in enumerate(discovery.items, start=1):
        print(
            f"ITEM {index}: title={item.title or '-'} "
            f"publication_date={item.publication_date or '-'} "
            f"host={urlparse(item.url).hostname or '-'}"
        )

    if not discovery.items or discovery.rejected_count:
        print("FINAL: REVIEW-REQUIRED - MoSPI API did not return a clean bounded discovery set.")
        return
    print(
        "FINAL: PASS-READ-ONLY - the official MoSPI API returned bounded first-party PDF "
        "discovery. No discovered PDF was fetched and no PostgreSQL/B2/Qdrant state changed."
    )


if __name__ == "__main__":
    main()

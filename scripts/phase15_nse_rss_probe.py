import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.ingestion.downloader import download_trusted_document
from app.monitoring.discovery import discover_feed_items
from app.monitoring.feed_probe import assess_feed_probe
from app.sources.registry import validate_source_url

SOURCE_ID = "nse"
FEED_URL = "https://nsearchives.nseindia.com/content/RSS/Daily_Buyback.xml"
DISCOVERY_LIMIT = 10


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 15 read-only live probe for the official NSE Daily Buy Back RSS feed. "
            "The feed may be fetched once, but no discovered item URL is followed and "
            "no PostgreSQL, Backblaze B2, or Qdrant write is performed."
        )
    )
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    settings = get_settings()

    print("PHASE 15 NSE RSS ENDPOINT PROBE - READ ONLY")
    print(f"SOURCE: {SOURCE_ID}")
    print(f"FEED: {FEED_URL}")
    print(f"DISCOVERY LIMIT: {DISCOVERY_LIMIT}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    if settings.source_monitoring_enabled or settings.source_auto_ingest_enabled or settings.trust_promotion_enabled:
        print("FINAL: BLOCKED - all global monitoring/auto-ingest/trust gates must remain false for this probe.")
        return
    if not args.allow_network:
        print("FINAL: BLOCKED - --allow-network is required for the one read-only feed request.")
        return

    try:
        validate_source_url(SOURCE_ID, FEED_URL)
        downloaded = download_trusted_document(SOURCE_ID, FEED_URL)
        discovery = discover_feed_items(downloaded.content, source_id=SOURCE_ID, limit=DISCOVERY_LIMIT)
    except ConnectionError:
        print("FINAL: BLOCKED - NSE feed request failed with transient_network_error; no writes occurred.")
        return
    except Exception as exc:
        print(
            "FINAL: BLOCKED - NSE feed failed trusted-source or XML validation; "
            f"no writes occurred. error_type={type(exc).__name__}"
        )
        return

    print(
        "FEED RESULT: "
        f"content_type={downloaded.content_type} bytes={len(downloaded.content)} "
        f"sha256={downloaded.sha256} final_host={urlparse(downloaded.final_url).hostname or '-'}"
    )
    print(
        "DISCOVERY RESULT: "
        f"discovered={len(discovery.items)} rejected={discovery.rejected_count} "
        f"rejection_reasons={dict(discovery.rejection_reasons) or '-'}"
    )
    for index, item in enumerate(discovery.items, start=1):
        print(
            f"ITEM {index}: title={item.title or '-'} publication_date={item.publication_date or '-'} "
            f"host={urlparse(item.url).hostname or '-'}"
        )

    decision = assess_feed_probe(
        content_type=downloaded.content_type,
        discovered_count=len(discovery.items),
        rejected_count=discovery.rejected_count,
        limit=DISCOVERY_LIMIT,
    )
    if not decision.passed:
        print("FINAL: REVIEW-REQUIRED - NSE feed is not ready for monitor registration. blockers=" + ",".join(decision.blockers))
        return

    print(
        "FINAL: PASS-READ-ONLY - the official NSE RSS endpoint returned bounded, allow-listed XML "
        "discovery with no rejected items. No discovered item URL was fetched and no "
        "PostgreSQL/Backblaze B2/Qdrant state changed."
    )


if __name__ == "__main__":
    main()

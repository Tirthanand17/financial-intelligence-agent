import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.ingestion.chunker import chunk_text
from app.ingestion.downloader import download_trusted_document
from app.ingestion.extractor import extract_document
from app.ingestion.quality import validate_extracted_document
from app.monitoring.registry import get_monitor
from app.sources.metadata import extract_source_publication_date
from app.sources.sebi import extract_sebi_primary_pdf_url
from app.storage.database import SourceMonitorDiscoveryRecord, get_session


def _host(url: str) -> str:
    return (urlparse(url).hostname or "-").lower()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Phase 15 diagnostic for one pending SEBI discovery. "
            "At most the detail wrapper and one approved first-party PDF are fetched."
        )
    )
    parser.add_argument("--monitor-id", default="sebi-rss")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for at most two first-party SEBI GETs.",
    )
    args = parser.parse_args()

    if not args.allow_network:
        print("BLOCKED: --allow-network is required; no network calls were made.")
        return

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false.")
        return
    if settings.source_auto_ingest_enabled:
        print("BLOCKED: SOURCE_AUTO_INGEST_ENABLED must remain false.")
        return
    if settings.trust_promotion_enabled:
        print("BLOCKED: TRUST_PROMOTION_ENABLED must remain false.")
        return

    monitor = get_monitor(args.monitor_id)
    if monitor.source_id != "sebi":
        print("BLOCKED: this diagnostic is restricted to the registered SEBI monitor.")
        return

    print("PHASE 15 SEBI EVIDENCE DIAGNOSTIC - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print("FETCH BOUND: one detail wrapper plus at most one approved SEBI PDF")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")

    with get_session() as session:
        record = session.scalar(
            select(SourceMonitorDiscoveryRecord)
            .where(
                SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
                SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
                SourceMonitorDiscoveryRecord.status == "pending",
            )
            .order_by(
                SourceMonitorDiscoveryRecord.first_seen_at,
                SourceMonitorDiscoveryRecord.id,
            )
            .limit(1)
        )
        if record is None:
            print("FINAL: BLOCKED - no pending SEBI discovery is available.")
            return

        print(f"QUEUE ITEM: title={record.title or '-'} publication_date={record.publication_date or '-'}")

        try:
            wrapper = download_trusted_document(record.source_id, record.url)
        except ConnectionError:
            print("FINAL: REVIEW-REQUIRED reason=wrapper_transient_network_error")
            return
        except Exception as exc:
            print(f"FINAL: REVIEW-REQUIRED reason=wrapper_download_{type(exc).__name__}")
            return

        try:
            wrapper_extracted = extract_document(wrapper.content, wrapper.content_type)
            validate_extracted_document(wrapper_extracted, wrapper.content_type)
        except Exception as exc:
            print(f"WRAPPER: content_type={wrapper.content_type} bytes={len(wrapper.content)} host={_host(wrapper.final_url)}")
            print(f"FINAL: REVIEW-REQUIRED reason=wrapper_validation_{type(exc).__name__}")
            return

        wrapper_date = extract_source_publication_date("sebi", wrapper_extracted.text)
        print(
            "WRAPPER: "
            f"content_type={wrapper.content_type} bytes={len(wrapper.content)} "
            f"text_chars={len(wrapper_extracted.text)} host={_host(wrapper.final_url)} "
            f"publication_date={wrapper_date or '-'}"
        )

        try:
            attachment_url = extract_sebi_primary_pdf_url(wrapper.content, wrapper.final_url)
        except ValueError:
            print("ATTACHMENT RESOLUTION: status=ambiguous")
            print("FINAL: REVIEW-REQUIRED reason=multiple_approved_pdf_candidates")
            return

        if attachment_url is None:
            print("ATTACHMENT RESOLUTION: status=none")
            print("FINAL: REVIEW-REQUIRED reason=no_single_approved_pdf_candidate")
            return

        parsed_attachment = urlparse(attachment_url)
        print(
            "ATTACHMENT RESOLUTION: "
            f"status=single host={(parsed_attachment.hostname or '-').lower()} "
            f"path_class={'sebi_attachdocs_pdf' if parsed_attachment.path.startswith('/sebi_data/attachdocs/') else 'unexpected'}"
        )

        try:
            attachment = download_trusted_document("sebi", attachment_url)
        except ConnectionError:
            print("FINAL: REVIEW-REQUIRED reason=attachment_transient_network_error")
            return
        except Exception as exc:
            print(f"FINAL: REVIEW-REQUIRED reason=attachment_download_{type(exc).__name__}")
            return

        print(
            "ATTACHMENT DOWNLOAD: "
            f"content_type={attachment.content_type} bytes={len(attachment.content)} "
            f"host={_host(attachment.final_url)} sha256={attachment.sha256}"
        )

        if attachment.content_type != "application/pdf":
            print("FINAL: REVIEW-REQUIRED reason=attachment_not_pdf")
            return

        try:
            extracted = extract_document(attachment.content, attachment.content_type)
            validate_extracted_document(extracted, attachment.content_type)
            chunks = chunk_text(
                extracted.text,
                chunk_size=settings.chunk_size_chars,
                overlap=settings.chunk_overlap_chars,
            )
        except Exception as exc:
            print(f"FINAL: REVIEW-REQUIRED reason=attachment_validation_{type(exc).__name__}")
            return

        if not chunks:
            print("FINAL: REVIEW-REQUIRED reason=attachment_no_searchable_chunks")
            return

        print(
            "ATTACHMENT EVIDENCE: "
            f"text_chars={len(extracted.text)} chunks={len(chunks)} "
            f"publication_date={wrapper_date or '-'}"
        )
        print(
            "FINAL: PASS-READ-ONLY - one SEBI wrapper and one narrowly approved PDF "
            "were validated in memory. No queue, PostgreSQL evidence, Backblaze B2, "
            "Qdrant, claim, or trust state was changed."
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

from app.services.evidence_search import build_evidence_search_snapshot


EXPORT_FIELDS = [
    "claim_id",
    "document_id",
    "source_id",
    "entity",
    "metric",
    "canonical_metric",
    "indicator_id",
    "value_text",
    "value_numeric",
    "unit",
    "state",
    "confidence",
    "publication_date",
    "effective_date",
    "temporal_date",
    "temporal_basis",
    "quality_gate",
    "quality_rejection_reason",
    "source_url",
    "document_title",
    "document_source_name",
    "document_sha256",
    "document_content_type",
    "document_retrieved_at",
    "document_status",
    "evidence_excerpt",
]


def _flatten_claim(claim: dict[str, object]) -> dict[str, object]:
    document = claim.get("document")
    document_dict = document if isinstance(document, dict) else {}
    return {
        "claim_id": claim.get("claim_id"),
        "document_id": claim.get("document_id"),
        "source_id": claim.get("source_id"),
        "entity": claim.get("entity"),
        "metric": claim.get("metric"),
        "canonical_metric": claim.get("canonical_metric"),
        "indicator_id": claim.get("indicator_id"),
        "value_text": claim.get("value_text"),
        "value_numeric": claim.get("value_numeric"),
        "unit": claim.get("unit"),
        "state": claim.get("state"),
        "confidence": claim.get("confidence"),
        "publication_date": claim.get("publication_date"),
        "effective_date": claim.get("effective_date"),
        "temporal_date": claim.get("temporal_date"),
        "temporal_basis": claim.get("temporal_basis"),
        "quality_gate": claim.get("quality_gate"),
        "quality_rejection_reason": claim.get("quality_rejection_reason"),
        "source_url": claim.get("source_url"),
        "document_title": document_dict.get("title"),
        "document_source_name": document_dict.get("source_name"),
        "document_sha256": document_dict.get("sha256"),
        "document_content_type": document_dict.get("content_type"),
        "document_retrieved_at": document_dict.get("retrieved_at"),
        "document_status": document_dict.get("status"),
        "evidence_excerpt": claim.get("evidence_excerpt"),
    }


def build_claim_export(
    *,
    q: str | None = None,
    source_id: str | None = None,
    state: str | None = None,
    entity: str | None = None,
    metric: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    """Build a bounded read-only export from persisted claim evidence.

    The export deliberately reuses the existing evidence-search contract so date
    semantics, exact filters, normalization diagnostics, quality diagnostics and
    provenance handling remain identical to the inspected dashboard/search layer.
    """
    snapshot = build_evidence_search_snapshot(
        q=q,
        source_id=source_id,
        state=state,
        entity=entity,
        metric=metric,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    rows = [_flatten_claim(claim) for claim in snapshot["claims"]]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_claim_evidence_export",
        "scope": snapshot["scope"],
        "summary": {
            "matching_claims": snapshot["summary"]["claim_hits"],
            "returned_claims": len(rows),
            "has_more": snapshot["summary"]["claim_has_more"],
        },
        "fields": list(EXPORT_FIELDS),
        "rows": rows,
        "safety": {
            "read_only": True,
            "bounded": True,
            "max_rows_per_request": 100,
            "network_crawling": False,
            "mutates_data": False,
            "exposes_private_object_keys": False,
            "invented_dates": False,
            "trust_promotion": False,
            "note": (
                "Exports contain already-persisted structured evidence and safe provenance fields only. "
                "Private storage object keys are not exported."
            ),
        },
    }


def render_claim_export_csv(payload: dict[str, object]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in payload["rows"]:
        writer.writerow({field: row.get(field) for field in EXPORT_FIELDS})
    return output.getvalue()

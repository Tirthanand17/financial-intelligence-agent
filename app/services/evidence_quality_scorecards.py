from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

from app.claims.catalog import normalize_indicator_metric
from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.sources.registry import get_source
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    DocumentRecord,
    get_session,
)

MAX_SCANNED_CLAIMS = 20_000


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 1)


def _known_source(source_id: str) -> bool:
    try:
        get_source(source_id)
        return True
    except ValueError:
        return False


def build_evidence_quality_scorecards() -> dict[str, object]:
    """Return factual evidence-quality dimensions without a composite truth score."""
    with get_session() as session:
        claims = list(
            session.scalars(
                select(ClaimRecord)
                .order_by(ClaimRecord.created_at.asc(), ClaimRecord.id.asc())
                .limit(MAX_SCANNED_CLAIMS + 1)
            )
        )
        if len(claims) > MAX_SCANNED_CLAIMS:
            raise ValueError("claim scan exceeds the safety bound")
        attributions = list(session.scalars(select(ClaimEntityAttributionRecord)))
        document_ids = sorted({row.document_id for row in claims})
        documents = (
            list(
                session.scalars(
                    select(DocumentRecord).where(DocumentRecord.id.in_(document_ids))
                )
            )
            if document_ids
            else []
        )

    attribution_claim_ids = {row.claim_id for row in attributions}
    docs_by_id = {row.id: row for row in documents}
    terminal = {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}

    dimensions = (
        "quality_gate_pass",
        "temporal_scope_present",
        "entity_attribution_recorded",
        "linked_document_present",
        "document_sha_present",
        "raw_evidence_reference_present",
        "source_registry_known",
        "indicator_catalog_mapped",
    )
    overall: Counter[str] = Counter()
    per_source: dict[str, Counter[str]] = defaultdict(Counter)
    issue_examples: list[dict[str, object]] = []

    for claim in claims:
        active = claim.state not in terminal
        quality_pass = claim_quality_rejection_reason(claim.metric, claim.evidence_text) is None
        temporal_present = claim.effective_date is not None or claim.publication_date is not None
        attribution_present = claim.id in attribution_claim_ids
        document = docs_by_id.get(claim.document_id)
        linked_document_present = document is not None
        sha_present = bool(document and document.sha256)
        raw_reference_present = bool(document and document.object_key)
        source_known = _known_source(claim.source_id)
        indicator_mapped = normalize_indicator_metric(claim.metric).indicator_id is not None

        values = {
            "quality_gate_pass": quality_pass,
            "temporal_scope_present": temporal_present,
            "entity_attribution_recorded": attribution_present,
            "linked_document_present": linked_document_present,
            "document_sha_present": sha_present,
            "raw_evidence_reference_present": raw_reference_present,
            "source_registry_known": source_known,
            "indicator_catalog_mapped": indicator_mapped,
        }
        overall["claims_total"] += 1
        per_source[claim.source_id]["claims_total"] += 1
        if active:
            overall["claims_active"] += 1
            per_source[claim.source_id]["claims_active"] += 1
        for name, passed in values.items():
            if passed:
                overall[name] += 1
                per_source[claim.source_id][name] += 1

        missing = [name for name in dimensions if not values[name]]
        if missing and len(issue_examples) < 100:
            issue_examples.append(
                {
                    "claim_id": claim.id,
                    "source_id": claim.source_id,
                    "document_id": claim.document_id,
                    "entity": claim.entity,
                    "metric": claim.metric,
                    "state": claim.state,
                    "missing_dimensions": missing,
                }
            )

    def card(source_id: str | None, counts: Counter[str]) -> dict[str, object]:
        total = counts["claims_total"]
        return {
            "source_id": source_id,
            "claims_total": total,
            "claims_active": counts["claims_active"],
            "dimensions": {
                name: {
                    "present": counts[name],
                    "missing": max(total - counts[name], 0),
                    "percent_present": _percent(counts[name], total),
                }
                for name in dimensions
            },
        }

    source_cards = [card(source_id, counts) for source_id, counts in sorted(per_source.items())]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_factual_evidence_quality_scorecards",
        "overall": card(None, overall),
        "per_source": source_cards,
        "issue_examples": issue_examples,
        "dimension_definitions": {
            "quality_gate_pass": "Existing extraction-quality gate accepts the persisted metric/evidence text.",
            "temporal_scope_present": "A persisted effective date or publication date exists.",
            "entity_attribution_recorded": "Canonical entity-attribution provenance exists for the claim.",
            "linked_document_present": "The claim points to a persisted document row.",
            "document_sha_present": "The linked document has a persisted SHA-256 digest.",
            "raw_evidence_reference_present": "The linked document records that private raw evidence is retained; the object key is not exposed here.",
            "source_registry_known": "The claim source is present in the enabled trusted-source registry.",
            "indicator_catalog_mapped": "The persisted source metric matches a deterministic exact alias in the indicator catalog; unmapped does not mean invalid.",
        },
        "interpretation": {
            "composite_score": None,
            "ranking": False,
            "truth_probability": None,
            "note": (
                "These are factual completeness/quality dimensions, not a truth score, source ranking, "
                "or automatic verification/trust decision. Indicator mapping is informational and an "
                "unmapped source metric can still be valid evidence."
            ),
        },
        "safety": {
            "read_only": True,
            "mutates_claims": False,
            "mutates_documents": False,
            "exposes_object_keys": False,
            "enables_trust_promotion": False,
            "deletes_evidence": False,
        },
    }

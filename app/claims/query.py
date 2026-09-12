import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState
from app.storage.database import ClaimRecord


WORD_RE = re.compile(r"[A-Za-z0-9%₹$._-]+")
STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
    "was", "were", "what", "why", "how", "when", "which", "with", "from", "by",
    "shown", "show", "website", "site", "current", "currently", "latest", "value",
}


@dataclass(frozen=True, slots=True)
class StructuredClaimResolution:
    """Conservative structured-claim result for grounded question answering."""

    status: str
    answer: str
    confidence: str
    confidence_basis: str
    evidence: tuple[dict[str, object], ...]


def _normalized(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def _terms(value: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(value)
        if len(token) > 1 and token.lower() not in STOP_WORDS
    }


def _relevance(record: ClaimRecord, question: str, question_terms: set[str]) -> int:
    metric = _normalized(record.metric)
    metric_terms = _terms(record.metric)
    overlap = len(question_terms & metric_terms)
    if overlap == 0:
        return 0

    score = overlap * 10
    if metric and metric in _normalized(question):
        score += 25

    entity_overlap = len(question_terms & _terms(record.entity))
    score += entity_overlap * 2
    return score


def _temporal_date(record: ClaimRecord) -> date | None:
    return record.effective_date or record.publication_date


def _evidence(record: ClaimRecord) -> dict[str, object]:
    return {
        "claim_id": record.id,
        "document_id": record.document_id,
        "source_id": record.source_id,
        "source_url": record.source_url,
        "entity": record.entity,
        "metric": record.metric,
        "value": record.value_text,
        "unit": record.unit,
        "publication_date": record.publication_date.isoformat() if record.publication_date else None,
        "effective_date": record.effective_date.isoformat() if record.effective_date else None,
        "state": record.state,
        "text": record.evidence_text,
        "chunk_index": record.evidence_chunk_index,
    }


def resolve_structured_claim_question(
    session: Session,
    question: str,
    *,
    source_id: str | None = None,
) -> StructuredClaimResolution | None:
    """Resolve a factual question from persisted structured claims when safe.

    Rules:
    - require lexical overlap with the claim metric;
    - reject/refrain from using rejected or superseded claims as current facts;
    - prefer the latest explicit temporal scope when one exists;
    - surface conflicts instead of selecting one disputed value;
    - within one active scope prefer TRUSTED, then VERIFIED, then CANDIDATE;
    - never silently promote a candidate just because it is selected for QA.
    """
    question_terms = _terms(question)
    if not question_terms:
        return None

    statement = select(ClaimRecord)
    if source_id is not None:
        statement = statement.where(ClaimRecord.source_id == source_id)

    records = list(session.scalars(statement))
    scored = [
        (score, record)
        for record in records
        if (score := _relevance(record, question, question_terms)) > 0
    ]
    if not scored:
        return None

    best_score = max(score for score, _ in scored)
    matched = [record for score, record in scored if score == best_score]

    # Narrow to the same fact series as the strongest lexical match so a generic
    # term such as "rate" cannot combine unrelated metrics into one answer.
    anchor = matched[0]
    series_key = (
        _normalized(anchor.entity),
        _normalized(anchor.metric),
        _normalized(anchor.unit),
    )
    series = [
        record
        for _, record in scored
        if (
            _normalized(record.entity),
            _normalized(record.metric),
            _normalized(record.unit),
        )
        == series_key
    ]

    active = [
        record
        for record in series
        if record.state not in {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}
    ]
    if not active:
        # Known history exists, but there is no active structured fact to present
        # as current. Do not fall back to a superseded value.
        return StructuredClaimResolution(
            status="no_active_claim",
            answer=f"No active structured claim is available for {anchor.metric}.",
            confidence="low",
            confidence_basis="only_rejected_or_superseded_structured_claims",
            evidence=tuple(_evidence(record) for record in series),
        )

    dated = [record for record in active if _temporal_date(record) is not None]
    if dated:
        latest_date = max(_temporal_date(record) for record in dated)
        scope = [record for record in dated if _temporal_date(record) == latest_date]
    else:
        scope = [record for record in active if _temporal_date(record) is None]

    conflicted = [record for record in scope if record.state == ClaimState.CONFLICTED.value]
    distinct_values = {_normalized(record.value_text) for record in scope}
    if conflicted or len(distinct_values) > 1:
        return StructuredClaimResolution(
            status="conflict",
            answer=f"Conflicting structured claims exist for {anchor.metric}; no single value is presented as current fact.",
            confidence="low",
            confidence_basis="conflicting_structured_claims",
            evidence=tuple(_evidence(record) for record in scope),
        )

    rank = {
        ClaimState.TRUSTED.value: 3,
        ClaimState.VERIFIED.value: 2,
        ClaimState.CANDIDATE.value: 1,
    }
    eligible = [record for record in scope if record.state in rank]
    if not eligible:
        return None

    selected = max(eligible, key=lambda record: rank[record.state])
    if selected.state == ClaimState.TRUSTED.value:
        confidence = "high"
        basis = "trusted_structured_claim"
    elif selected.state == ClaimState.VERIFIED.value:
        confidence = "high"
        basis = "verified_structured_claim"
    else:
        confidence = "medium"
        basis = "candidate_structured_claim"

    return StructuredClaimResolution(
        status="answer",
        answer=f"{selected.metric} : {selected.value_text}",
        confidence=confidence,
        confidence_basis=basis,
        evidence=tuple(_evidence(record) for record in scope),
    )

from dataclasses import dataclass
from datetime import date

from app.claims.models import ClaimState, StructuredClaim


@dataclass(frozen=True, slots=True)
class SupersessionDecision:
    """Non-destructive decision about whether an older claim is replaced.

    Supersession is source-local version history, not cross-source verification.
    The older claim remains stored; a persistence layer may later change only its
    state to SUPERSEDED and record the replacing document/claim relationship.
    """

    state: ClaimState
    reason: str
    superseded_by_document_id: str | None = None
    temporal_kind: str | None = None
    older_date: date | None = None
    newer_date: date | None = None


def _normalized(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def _same_series(older: StructuredClaim, newer: StructuredClaim) -> bool:
    """Return whether two claims belong to the same source-local fact series."""
    return (
        older.source_id == newer.source_id
        and _normalized(older.entity) == _normalized(newer.entity)
        and _normalized(older.metric) == _normalized(newer.metric)
        and _normalized(older.unit) == _normalized(newer.unit)
    )


def _comparable_dates(
    older: StructuredClaim,
    newer: StructuredClaim,
) -> tuple[str, date, date] | None:
    """Use only matching temporal semantics for automatic supersession.

    Effective dates are preferred when both claims have them. Publication dates
    are used only when neither claim has an effective date and both publication
    dates are known. We do not compare an effective date with a publication date.
    """
    if older.effective_date is not None and newer.effective_date is not None:
        return ("effective", older.effective_date, newer.effective_date)

    if (
        older.effective_date is None
        and newer.effective_date is None
        and older.publication_date is not None
        and newer.publication_date is not None
    ):
        return ("publication", older.publication_date, newer.publication_date)

    return None


def assess_supersession(
    older: StructuredClaim,
    newer: StructuredClaim,
) -> SupersessionDecision:
    """Assess whether `newer` safely supersedes `older` without mutating either.

    Conservative Phase 2 rules:
    - rejected/superseded newer claims cannot replace history;
    - cross-source claims never supersede each other here (verification handles
      cross-source agreement/conflict instead);
    - entity, metric and unit must match;
    - a claim cannot supersede itself/the same document version;
    - temporal semantics must match and the newer date must be strictly later;
    - value equality does not block supersession: a later official snapshot may
      repeat the same value while still replacing the older current snapshot.
    """
    if older.state is ClaimState.REJECTED:
        return SupersessionDecision(
            state=older.state,
            reason="older_rejected_state_preserved",
        )

    if older.state is ClaimState.SUPERSEDED:
        return SupersessionDecision(
            state=ClaimState.SUPERSEDED,
            reason="already_superseded",
        )

    if newer.state in {
        ClaimState.REJECTED,
        ClaimState.SUPERSEDED,
        ClaimState.CONFLICTED,
    }:
        return SupersessionDecision(
            state=older.state,
            reason="newer_claim_not_eligible",
        )

    if older.document_id == newer.document_id:
        return SupersessionDecision(
            state=older.state,
            reason="same_document",
        )

    if not _same_series(older, newer):
        return SupersessionDecision(
            state=older.state,
            reason="different_series_or_source",
        )

    dates = _comparable_dates(older, newer)
    if dates is None:
        return SupersessionDecision(
            state=older.state,
            reason="incompatible_or_missing_temporal_scope",
        )

    temporal_kind, older_date, newer_date = dates
    if newer_date <= older_date:
        return SupersessionDecision(
            state=older.state,
            reason="newer_date_not_later",
            temporal_kind=temporal_kind,
            older_date=older_date,
            newer_date=newer_date,
        )

    return SupersessionDecision(
        state=ClaimState.SUPERSEDED,
        reason="newer_source_local_version",
        superseded_by_document_id=newer.document_id,
        temporal_kind=temporal_kind,
        older_date=older_date,
        newer_date=newer_date,
    )

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.claims.entities import normalize_metric_for_entity, resolve_entity
from app.claims.models import ClaimState, StructuredClaim
from app.claims.temporal import extract_temporal_metadata


# Structured extraction remains deliberately conservative. Only explicit numeric
# key/value facts are accepted; free-form prose extraction is a later concern.
_NUMBER_WITH_OPTIONAL_UNIT = (
    r"(?:₹|\$|€)?\s*[-+]?\d[\d,.]*"
    r"\s*(?:%|bps|basis points|crore|lakh|million|billion|trillion)?"
)

STRUCTURED_FACT_RE = re.compile(
    r"(?P<metric>[A-Za-z][A-Za-z0-9 /&().,'’\-]{1,100}?)\s*:\s*"
    rf"(?P<value>{_NUMBER_WITH_OPTIONAL_UNIT}"
    rf"(?:\s*(?:-|–|to)\s*{_NUMBER_WITH_OPTIONAL_UNIT})?)",
    re.IGNORECASE,
)

VALUE_ONLY_RE = re.compile(
    rf"^(?P<value>{_NUMBER_WITH_OPTIONAL_UNIT}"
    rf"(?:\s*(?:-|–|to)\s*{_NUMBER_WITH_OPTIONAL_UNIT})?)$",
    re.IGNORECASE,
)

LABEL_ONLY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 /&().,'’\-]{1,100}$")
PERIOD_ONLY_RE = re.compile(r"^\d{4}\s*[-–]\s*\d{2,4}$")


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _unit_from_value(value_text: str) -> str | None:
    lowered = value_text.lower()
    if "%" in value_text:
        return "%"
    if lowered.endswith("bps") or lowered.endswith("basis points"):
        return "bps"
    for unit in ("crore", "lakh", "million", "billion", "trillion"):
        if lowered.endswith(unit):
            return unit
    if value_text.startswith("₹"):
        return "INR"
    if value_text.startswith("$"):
        return "USD"
    if value_text.startswith("€"):
        return "EUR"
    return None


def _numeric_value(value_text: str) -> Decimal | None:
    """Parse only an unambiguous scalar number.

    Ranges such as `8.40% - 10.00%` deliberately remain text-only because one
    scalar Decimal would misrepresent the source.
    """
    body = value_text.strip()
    body = re.sub(r"^(?:₹|\$|€)\s*", "", body)
    body = re.sub(
        r"\s*(?:%|bps|basis points|crore|lakh|million|billion|trillion)\s*$",
        "",
        body,
        flags=re.IGNORECASE,
    )
    if re.search(r"\s(?:-|–|to)\s", body, flags=re.IGNORECASE):
        return None
    try:
        return Decimal(body.replace(",", ""))
    except InvalidOperation:
        return None


def _is_period_only_value(value_text: str) -> bool:
    """Reject year/financial-period labels that look numeric but are not facts."""
    return PERIOD_ONLY_RE.fullmatch(value_text.strip()) is not None


def _local_window_text(
    *,
    clean_lines: list[str],
    start_index: int,
    end_index: int,
) -> str:
    # Temporal metadata stays intentionally tight so a date from an unrelated
    # nearby section is not inherited by a claim.
    window_start = max(0, start_index - 2)
    window_end = min(len(clean_lines), end_index + 3)
    return "\n".join(clean_lines[window_start:window_end])


def _local_temporal_dates(
    *,
    clean_lines: list[str],
    start_index: int,
    end_index: int,
    publication_date: date | None,
    effective_date: date | None,
) -> tuple[date | None, date | None]:
    """Attach only explicitly labelled dates close to one claim."""
    local_text = _local_window_text(
        clean_lines=clean_lines,
        start_index=start_index,
        end_index=end_index,
    )
    metadata = extract_temporal_metadata(local_text)
    return (
        publication_date if publication_date is not None else metadata.publication_date,
        effective_date if effective_date is not None else metadata.effective_date,
    )


def _local_entity_context(
    *,
    clean_lines: list[str],
    start_index: int,
    end_index: int,
    default_entity: str,
    metric: str,
) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]:
    """Resolve and fully describe the local canonical-subject decision.

    Entity section headers often sit a few lines above a dated fact, so entity
    attribution gets a slightly wider backward window than temporal parsing.
    Ambiguous windows still default to the source entity rather than guessing.
    The exact normalized window used for the decision is returned for audit
    persistence; it is not silently expanded to the whole chunk/document.
    """
    window_start = max(0, start_index - 4)
    window_end = min(len(clean_lines), end_index + 3)
    local_text = "\n".join(clean_lines[window_start:window_end])
    resolution = resolve_entity(local_text, default_entity=default_entity)
    canonical_metric = normalize_metric_for_entity(
        metric,
        canonical_entity=resolution.canonical_name,
    )
    return (
        resolution.canonical_name,
        canonical_metric,
        resolution.basis,
        resolution.matched_aliases,
        resolution.ambiguous_candidates,
        local_text,
    )


def _append_claim(
    *,
    claims: list[StructuredClaim],
    seen: set[tuple[str, str, str, int]],
    metric: str,
    value_text: str,
    evidence_text: str,
    chunk_index: int,
    document_id: str,
    source_id: str,
    source_url: str,
    entity: str,
    entity_attribution_basis: str,
    entity_source_default: str,
    entity_matched_aliases: tuple[str, ...],
    entity_ambiguous_candidates: tuple[str, ...],
    entity_evidence_text: str,
    publication_date: date | None,
    effective_date: date | None,
) -> None:
    if _is_period_only_value(value_text):
        return

    key = (entity.lower(), metric.lower(), value_text.lower(), chunk_index)
    if key in seen:
        return
    seen.add(key)

    claims.append(
        StructuredClaim(
            entity=entity,
            metric=metric,
            value_text=value_text,
            value_numeric=_numeric_value(value_text),
            unit=_unit_from_value(value_text),
            publication_date=publication_date,
            effective_date=effective_date,
            source_id=source_id,
            source_url=source_url,
            document_id=document_id,
            evidence_text=evidence_text,
            evidence_chunk_index=chunk_index,
            entity_attribution_basis=entity_attribution_basis,
            entity_source_default=entity_source_default,
            entity_matched_aliases=entity_matched_aliases,
            entity_ambiguous_candidates=entity_ambiguous_candidates,
            entity_evidence_text=entity_evidence_text,
            confidence=0.95,
            state=ClaimState.CANDIDATE,
        )
    )


def extract_structured_claims(
    *,
    chunks: list[str],
    document_id: str,
    source_id: str,
    source_url: str,
    entity: str,
    publication_date: date | None = None,
    effective_date: date | None = None,
) -> list[StructuredClaim]:
    """Extract explicit numeric key/value facts from already-trusted evidence.

    Evidence may be on one line (`Metric : Value`) or in a conservative
    three-line HTML-table form (`Metric`, `:`, `Value`). Dates and canonical
    subject entities are attached only from small local evidence windows. A
    secondary source can therefore corroborate a primary-source fact only when
    it explicitly names one unambiguous known subject near that fact.

    Entity attribution provenance is carried with each extracted claim so the
    persistence layer can audit whether the subject came from an explicit local
    alias, an ambiguous local window, or the source default.

    New claims are candidates only; extraction never implies independent
    verification or promotion to trusted knowledge.
    """
    claims: list[StructuredClaim] = []
    seen: set[tuple[str, str, str, int]] = set()

    for chunk_index, chunk in enumerate(chunks):
        raw_lines = chunk.splitlines()
        clean_lines = [_clean_text(raw_line) for raw_line in raw_lines]

        # Standard one-line form, for example: `Policy Repo Rate : 5.25%`.
        for line_index, (raw_line, line) in enumerate(
            zip(raw_lines, clean_lines, strict=True)
        ):
            if not line:
                continue

            for match in STRUCTURED_FACT_RE.finditer(line):
                raw_metric = _clean_text(match.group("metric"))
                value_text = _clean_text(match.group("value"))
                local_publication_date, local_effective_date = _local_temporal_dates(
                    clean_lines=clean_lines,
                    start_index=line_index,
                    end_index=line_index,
                    publication_date=publication_date,
                    effective_date=effective_date,
                )
                (
                    local_entity,
                    metric,
                    entity_basis,
                    matched_aliases,
                    ambiguous_candidates,
                    entity_evidence_text,
                ) = _local_entity_context(
                    clean_lines=clean_lines,
                    start_index=line_index,
                    end_index=line_index,
                    default_entity=entity,
                    metric=raw_metric,
                )
                _append_claim(
                    claims=claims,
                    seen=seen,
                    metric=metric,
                    value_text=value_text,
                    evidence_text=_clean_text(raw_line),
                    chunk_index=chunk_index,
                    document_id=document_id,
                    source_id=source_id,
                    source_url=source_url,
                    entity=local_entity,
                    entity_attribution_basis=entity_basis,
                    entity_source_default=entity,
                    entity_matched_aliases=matched_aliases,
                    entity_ambiguous_candidates=ambiguous_candidates,
                    entity_evidence_text=entity_evidence_text,
                    publication_date=local_publication_date,
                    effective_date=local_effective_date,
                )

        # RBI-style HTML tables can extract as three separate lines:
        # `Policy Repo Rate`, `:`, `5.25%`. Only accept this split form when the
        # separator is explicit and the value carries a recognized financial
        # unit/currency; this prevents nearby navigation text from being paired.
        for index in range(len(clean_lines) - 2):
            raw_metric = clean_lines[index]
            separator = clean_lines[index + 1]
            value_line = clean_lines[index + 2]

            if separator != ":" or not LABEL_ONLY_RE.fullmatch(raw_metric):
                continue

            value_match = VALUE_ONLY_RE.fullmatch(value_line)
            if value_match is None:
                continue

            value_text = _clean_text(value_match.group("value"))
            if _unit_from_value(value_text) is None:
                continue

            evidence_text = "\n".join(
                (
                    _clean_text(raw_lines[index]),
                    _clean_text(raw_lines[index + 1]),
                    _clean_text(raw_lines[index + 2]),
                )
            )
            local_publication_date, local_effective_date = _local_temporal_dates(
                clean_lines=clean_lines,
                start_index=index,
                end_index=index + 2,
                publication_date=publication_date,
                effective_date=effective_date,
            )
            (
                local_entity,
                metric,
                entity_basis,
                matched_aliases,
                ambiguous_candidates,
                entity_evidence_text,
            ) = _local_entity_context(
                clean_lines=clean_lines,
                start_index=index,
                end_index=index + 2,
                default_entity=entity,
                metric=raw_metric,
            )
            _append_claim(
                claims=claims,
                seen=seen,
                metric=metric,
                value_text=value_text,
                evidence_text=evidence_text,
                chunk_index=chunk_index,
                document_id=document_id,
                source_id=source_id,
                source_url=source_url,
                entity=local_entity,
                entity_attribution_basis=entity_basis,
                entity_source_default=entity,
                entity_matched_aliases=matched_aliases,
                entity_ambiguous_candidates=ambiguous_candidates,
                entity_evidence_text=entity_evidence_text,
                publication_date=local_publication_date,
                effective_date=local_effective_date,
            )

    return claims

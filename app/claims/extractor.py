import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.claims.models import ClaimState, StructuredClaim


# Phase 2 starts conservatively with explicit key/value facts such as
# `Policy Repo Rate : 5.25%`. Free-form prose extraction comes later and must
# not be allowed to invent values that are not visible in the evidence.
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


def _append_claim(
    *,
    claims: list[StructuredClaim],
    seen: set[tuple[str, str, int]],
    metric: str,
    value_text: str,
    evidence_text: str,
    chunk_index: int,
    document_id: str,
    source_id: str,
    source_url: str,
    entity: str,
    publication_date: date | None,
    effective_date: date | None,
) -> None:
    if _is_period_only_value(value_text):
        return

    key = (metric.lower(), value_text.lower(), chunk_index)
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
    three-line HTML-table form (`Metric`, `:`, `Value`). Every claim keeps the
    exact supporting text sequence and chunk index. New claims are candidates
    only; extraction does not mean the fact has been independently verified or
    promoted to trusted knowledge.
    """
    claims: list[StructuredClaim] = []
    seen: set[tuple[str, str, int]] = set()

    for chunk_index, chunk in enumerate(chunks):
        raw_lines = chunk.splitlines()
        clean_lines = [_clean_text(raw_line) for raw_line in raw_lines]

        # Standard one-line form, for example: `Policy Repo Rate : 5.25%`.
        for raw_line, line in zip(raw_lines, clean_lines, strict=True):
            if not line:
                continue

            for match in STRUCTURED_FACT_RE.finditer(line):
                metric = _clean_text(match.group("metric"))
                value_text = _clean_text(match.group("value"))
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
                    entity=entity,
                    publication_date=publication_date,
                    effective_date=effective_date,
                )

        # RBI's HTML rate table currently extracts as three separate lines:
        # `Policy Repo Rate`, `:`, `5.25%`. Only accept this split form when the
        # separator is explicit and the value carries a recognized financial
        # unit/currency; this prevents nearby navigation text from being paired.
        for index in range(len(clean_lines) - 2):
            metric = clean_lines[index]
            separator = clean_lines[index + 1]
            value_line = clean_lines[index + 2]

            if separator != ":" or not LABEL_ONLY_RE.fullmatch(metric):
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
                entity=entity,
                publication_date=publication_date,
                effective_date=effective_date,
            )

    return claims

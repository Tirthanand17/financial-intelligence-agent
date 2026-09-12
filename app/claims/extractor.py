import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.claims.models import ClaimState, StructuredClaim


# Phase 2 starts conservatively with explicit key/value facts such as
# `Policy Repo Rate : 5.25%`. Free-form prose extraction comes later and must
# not be allowed to invent values that are not visible in the evidence.
STRUCTURED_FACT_RE = re.compile(
    r"(?P<metric>[A-Za-z][A-Za-z0-9 /&().,'’\-]{1,100}?)\s*:\s*"
    r"(?P<value>(?:₹|\$|€)?\s*[-+]?\d[\d,.]*"
    r"(?:\s*(?:-|–|to)\s*[-+]?\d[\d,.]*)?"
    r"\s*(?:%|bps|basis points|crore|lakh|million|billion|trillion)?)",
    re.IGNORECASE,
)


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

    Every claim keeps the exact supporting line and chunk index. New claims are
    candidates only; extraction does not mean the fact has been independently
    verified or promoted to trusted knowledge.
    """
    claims: list[StructuredClaim] = []
    seen: set[tuple[str, str, int]] = set()

    for chunk_index, chunk in enumerate(chunks):
        for raw_line in chunk.splitlines():
            line = _clean_text(raw_line)
            if not line:
                continue

            for match in STRUCTURED_FACT_RE.finditer(line):
                metric = _clean_text(match.group("metric"))
                value_text = _clean_text(match.group("value"))
                key = (metric.lower(), value_text.lower(), chunk_index)
                if key in seen:
                    continue
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
                        evidence_text=line,
                        evidence_chunk_index=chunk_index,
                        confidence=0.95,
                        state=ClaimState.CANDIDATE,
                    )
                )

    return claims

import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class TemporalMetadata:
    """Explicit temporal metadata found in source evidence.

    Dates are never inferred from retrieval time. Only dates explicitly labelled
    as publication/effective metadata are returned. Ambiguous conflicting dates
    are withheld instead of choosing one silently.
    """

    publication_date: date | None = None
    effective_date: date | None = None


_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

_DATE_TOKEN_RE = re.compile(
    rf"(?P<date>"
    rf"\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{4}}"
    rf"|\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}"
    rf"|(?:{_MONTHS})\s+\d{{1,2}}(?:,)?\s+\d{{4}}"
    rf")",
    re.IGNORECASE,
)

_EFFECTIVE_MARKER_RE = re.compile(
    r"\b(?:effective(?:\s+from|\s+date)?|with\s+effect\s+from|w\.?\s*e\.?\s*f\.?)\b",
    re.IGNORECASE,
)

_PUBLICATION_MARKER_RE = re.compile(
    r"\b(?:published(?:\s+on)?|publication\s+date|date\s+of\s+publication|dated)\b",
    re.IGNORECASE,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
)


def _normalize_date_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(",", " ")).strip()


def _parse_date(value: str) -> date | None:
    normalized = _normalize_date_text(value)
    # `Sept` is common in financial documents but Python's `%b` expects `Sep`.
    normalized = re.sub(r"\bSept\b", "Sep", normalized, flags=re.IGNORECASE)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _date_in_text(text: str) -> date | None:
    match = _DATE_TOKEN_RE.search(text)
    if match is None:
        return None
    return _parse_date(match.group("date"))


def _unique_or_none(values: list[date]) -> date | None:
    unique = set(values)
    if len(unique) == 1:
        return next(iter(unique))
    return None


def extract_temporal_metadata(text: str) -> TemporalMetadata:
    """Extract only explicitly labelled publication/effective dates.

    Supported evidence includes same-line forms such as `Published on 12
    September 2026` and conservative split forms such as `Publication Date` on
    one line followed immediately by `2026-09-12` on the next non-empty line.
    Unlabelled dates are ignored, and multiple conflicting dates of one type are
    treated as ambiguous rather than guessed.
    """
    raw_lines = text.splitlines()
    lines = [line.strip() for line in raw_lines]

    publication_dates: list[date] = []
    effective_dates: list[date] = []

    for index, line in enumerate(lines):
        if not line:
            continue

        effective_marker = _EFFECTIVE_MARKER_RE.search(line) is not None
        publication_marker = _PUBLICATION_MARKER_RE.search(line) is not None
        if not effective_marker and not publication_marker:
            continue

        parsed = _date_in_text(line)
        if parsed is None:
            # Permit a label/value split only when the next non-empty line is
            # immediately adjacent in semantic content and contains only a date.
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index]:
                next_index += 1
            if next_index < len(lines):
                next_line = lines[next_index]
                next_match = _DATE_TOKEN_RE.fullmatch(next_line)
                if next_match is not None:
                    parsed = _parse_date(next_match.group("date"))

        if parsed is None:
            continue

        if effective_marker:
            effective_dates.append(parsed)
        if publication_marker:
            publication_dates.append(parsed)

    return TemporalMetadata(
        publication_date=_unique_or_none(publication_dates),
        effective_date=_unique_or_none(effective_dates),
    )

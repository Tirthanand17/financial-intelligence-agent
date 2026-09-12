import re
from datetime import date, datetime


_RBI_DATE_RE = re.compile(
    r"^\s*Date\s*:\s*(?P<date>[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_DDNEWS_DATE_RE = re.compile(
    r"^\s*(?P<date>\d{2}/\d{2}/\d{2})\s*\|\s*"
    r"\d{1,2}:\d{2}\s*(?:am|pm)\s*\|",
    re.IGNORECASE | re.MULTILINE,
)

_AKASHVANI_DATE_RE = re.compile(
    r"^\s*News\s+On\s+AIR\s*\|\s*"
    r"(?P<date>[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s+"
    r"\d{1,2}:\d{2}\s*(?:am|pm)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_date(value: str, formats: tuple[str, ...]) -> date | None:
    cleaned = " ".join(value.split()).strip()
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def extract_source_publication_date(source_id: str, text: str) -> date | None:
    """Extract a page-level publication date only from source-specific evidence.

    This deliberately avoids a generic document-wide date heuristic. A date is
    returned only when the source has a stable, unambiguous page-level pattern
    that is safe to apply to all claims extracted from that document.

    Supported Phase 4 adapters:
    - RBI press releases/statements with a visible `Date : Jun 05, 2026` line.
    - DD News articles with a visible `05/06/26 | 12:23 pm | ...` article line.
    - Akashvani News articles with `News On AIR | June 5, 2026 2:35 PM`.

    Retrieval time is never used as publication time.
    """
    head = "\n".join(text.splitlines()[:120])

    if source_id == "rbi":
        match = _RBI_DATE_RE.search(head)
        if match is None:
            return None
        return _parse_date(
            match.group("date"),
            ("%b %d, %Y", "%B %d, %Y"),
        )

    if source_id == "ddnews":
        match = _DDNEWS_DATE_RE.search(head)
        if match is None:
            return None
        return _parse_date(match.group("date"), ("%d/%m/%y",))

    if source_id == "akashvani":
        match = _AKASHVANI_DATE_RE.search(head)
        if match is None:
            return None
        return _parse_date(
            match.group("date"),
            ("%B %d, %Y", "%b %d, %Y"),
        )

    return None

from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.sources.registry import validate_source_url


_SEBI_ATTACHMENT_PREFIX = "/sebi_data/attachdocs/"


def _normalize_pdf_candidate(page_url: str, href: str) -> str | None:
    """Return one explicit first-party SEBI PDF URL or ``None``.

    SEBI detail pages commonly expose attachments either as a direct
    ``/sebi_data/attachdocs/...pdf`` link or through the official ``/web/?file=``
    viewer wrapper. This helper never fetches a link. It only resolves and
    validates the target against the existing SEBI source allow-list and the
    narrowly approved attachment path.
    """
    absolute = urljoin(page_url, href.strip())
    parsed = urlparse(absolute)

    candidate = absolute
    if parsed.path.rstrip("/") == "/web":
        values = parse_qs(parsed.query).get("file", [])
        if len(values) != 1:
            return None
        candidate = unquote(values[0]).strip()

    candidate_parsed = urlparse(candidate)
    if candidate_parsed.scheme != "https":
        return None
    if not candidate_parsed.path.startswith(_SEBI_ATTACHMENT_PREFIX):
        return None
    if not candidate_parsed.path.lower().endswith(".pdf"):
        return None

    try:
        validate_source_url("sebi", candidate)
    except ValueError:
        return None
    return candidate


def extract_sebi_primary_pdf_url(content: bytes, page_url: str) -> str | None:
    """Extract at most one approved SEBI PDF attachment from a detail page.

    The function is intentionally fail-closed: arbitrary links are ignored,
    non-SEBI hosts are rejected by source policy, and multiple distinct approved
    PDF candidates are treated as ambiguous rather than choosing one silently.
    """
    soup = BeautifulSoup(content, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        candidate = _normalize_pdf_candidate(page_url, str(anchor.get("href", "")))
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)

    if len(candidates) > 1:
        raise ValueError("SEBI detail page exposes multiple approved PDF attachments")
    return candidates[0] if candidates else None

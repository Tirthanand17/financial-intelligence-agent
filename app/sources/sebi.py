import html
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.sources.registry import validate_source_url


_SEBI_ATTACHMENT_PREFIX = "/sebi_data/attachdocs/"
_SEBI_LINK_ATTRIBUTES = (
    "href",
    "src",
    "data-href",
    "data-url",
    "data-src",
    "data-file",
    "onclick",
)

# SEBI detail pages do not always expose the document target as a plain href.
# Some pages use the official /web/?file= viewer from another link-bearing
# attribute or from a small JavaScript handler. We never execute JavaScript.
# Instead, we extract only URL-shaped substrings and still require the final
# evidence target to pass the narrow first-party attachment policy below.
#
# The leading negative lookbehind is important: it prevents the scanner from
# carving a safe-looking relative ``/sebi_data/...`` or ``/web/...`` substring
# out of an absolute URL that belongs to another host (for example,
# ``https://example.com/sebi_data/...``). The complete external URL is still
# considered separately and then rejected by the normal source allow-list.
_TOKEN_BOUNDARY_RE = r"(?<![A-Za-z0-9._-])"
_VIEWER_TOKEN_RE = re.compile(
    _TOKEN_BOUNDARY_RE
    + r"(?:https://(?:www\.)?sebi\.gov\.in)?/web/\?file=[^\s'\"<>\\)]+",
    re.IGNORECASE,
)
_DIRECT_PDF_TOKEN_RE = re.compile(
    _TOKEN_BOUNDARY_RE
    + r"(?:https://(?:www\.)?sebi\.gov\.in)?"
    r"/sebi_data/attachdocs/[^\s'\"<>\\)]+?\.pdf(?:\?[^\s'\"<>\\)]*)?",
    re.IGNORECASE,
)


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


def _decoded_variants(value: str) -> list[str]:
    """Return bounded HTML/percent-decoded variants for structural URL search."""
    current = html.unescape(value.strip())
    variants = [current]
    for _ in range(2):
        decoded = unquote(current)
        if decoded == current:
            break
        variants.append(decoded)
        current = decoded
    return variants


def _candidate_tokens(value: str) -> list[str]:
    """Extract only SEBI viewer/direct-PDF shaped tokens from one attribute."""
    tokens: list[str] = []
    seen: set[str] = set()

    for variant in _decoded_variants(value):
        # A plain href/src may already be exactly the candidate. Embedded tokens
        # are additionally extracted, but the token regexes refuse to start in
        # the middle of an external hostname.
        for token in (
            variant,
            *_VIEWER_TOKEN_RE.findall(variant),
            *_DIRECT_PDF_TOKEN_RE.findall(variant),
        ):
            cleaned = token.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                tokens.append(cleaned)
    return tokens


def extract_sebi_primary_pdf_url(content: bytes, page_url: str) -> str | None:
    """Extract at most one approved SEBI PDF attachment from a detail page.

    The function is intentionally fail-closed. It does not execute JavaScript or
    follow arbitrary page links. It examines only a bounded set of link-bearing
    HTML attributes and accepts a target only when it resolves to HTTPS on the
    existing SEBI allow-list under ``/sebi_data/attachdocs/`` with a ``.pdf``
    suffix. Multiple distinct approved PDFs remain ambiguous and are rejected.
    """
    soup = BeautifulSoup(content, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all(True):
        for attribute in _SEBI_LINK_ATTRIBUTES:
            raw_value = tag.get(attribute)
            if raw_value is None:
                continue
            values = raw_value if isinstance(raw_value, list) else [raw_value]
            for value in values:
                for token in _candidate_tokens(str(value)):
                    candidate = _normalize_pdf_candidate(page_url, token)
                    if candidate is None or candidate in seen:
                        continue
                    seen.add(candidate)
                    candidates.append(candidate)

    if len(candidates) > 1:
        raise ValueError("SEBI detail page exposes multiple approved PDF attachments")
    return candidates[0] if candidates else None

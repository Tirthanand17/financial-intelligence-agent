import re

from app.claims.models import StructuredClaim
from app.sources.registry import get_source


# Exact normalized labels that are common document/page/contact metadata rather
# than financial/economic facts. Keep this list intentionally narrow: a metric is
# rejected only when its normalized label exactly matches one of these values.
_NON_FACT_METRICS = {
    "date",
    "email",
    "email id",
    "fax",
    "fax no",
    "fax number",
    "gstin",
    "last updated",
    "page no",
    "page number",
    "phone no",
    "phone number",
    "posted on",
    "release id",
    "serial no",
    "serial number",
    "s no",
    "s. no",
    "sr no",
    "sr. no",
    "scrip code",
    "telephone",
    "telephone no",
    "telephone number",
    "time",
    "toll free",
    "toll free no",
    "toll free number",
    "visitor counter",
    "website",
    "website url",
}
_MONTH_HEADING_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4}\b",
    re.IGNORECASE,
)
# Observed parser noise such as ``r.`` and ``i r.`` is deliberately narrower
# than a generic short-metric rule so legitimate abbreviations such as OI or PE
# are not rejected merely because they contain two letters.
_SHORT_FRAGMENT_RE = re.compile(r"^[A-Za-z](?:\s+[A-Za-z])?\.?$")
_TIME_TOKEN_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
# Page/serial labels sometimes carry punctuation or a numeric suffix after text
# extraction. This remains anchored to known metadata stems and does not reject
# generic numbered financial metrics.
_METADATA_LABEL_RE = re.compile(
    r"^(?:page|serial|sr\.?|s\.?)\s*(?:no\.?|number)?\s*\d*$",
    re.IGNORECASE,
)


def _normalized(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def claim_quality_rejection_reason(metric: str, evidence_text: str) -> str | None:
    """Return a narrow quality reason for obvious non-fact parser output.

    This filter operates only on derived structured candidates. Source documents,
    exact evidence bytes, chunks, and historical claim rows are never deleted or
    rewritten by this function.
    """
    normalized_metric = _normalized(metric)
    if normalized_metric in _NON_FACT_METRICS:
        return "metadata_metric"

    if _METADATA_LABEL_RE.fullmatch(metric.strip()):
        return "metadata_metric"

    if _SHORT_FRAGMENT_RE.fullmatch(metric.strip()):
        return "short_metric_fragment"

    if _MONTH_HEADING_RE.search(metric.strip()):
        return "month_heading_fragment"

    # Schedule prose with multiple clock times can be misread as key/value facts
    # because each time contains a colon. Such lines are not financial claims.
    if len(_TIME_TOKEN_RE.findall(evidence_text)) >= 2:
        return "schedule_time_fragment"

    return None


def is_claim_eligible(claim: StructuredClaim) -> bool:
    """Return whether an extracted claim is safe to persist as a candidate.

    Phase 16 first applies a narrow quality floor that removes obvious page
    metadata and parser fragments while preserving the source evidence. The
    existing policy-repo-rate subject rule then prevents secondary reporting from
    silently assigning the central-bank metric to the publisher itself.
    """
    if claim_quality_rejection_reason(claim.metric, claim.evidence_text) is not None:
        return False

    if _normalized(claim.metric) != "policy repo rate":
        return True

    try:
        source = get_source(claim.source_id)
    except ValueError:
        # Production ingestion validates source IDs before this point. Synthetic
        # unit/integration sources remain neutral here.
        return True

    source_is_subject = _normalized(source.name) == _normalized(claim.entity)
    if source_is_subject:
        return (
            source.category == "central_bank"
            and claim.entity_attribution_basis
            in {"source_default", "explicit_local_alias"}
        )

    return claim.entity_attribution_basis == "explicit_local_alias"


def filter_eligible_claims(claims: list[StructuredClaim]) -> list[StructuredClaim]:
    """Preserve order while dropping unsafe structured candidates."""
    return [claim for claim in claims if is_claim_eligible(claim)]

import re

from app.claims.models import StructuredClaim
from app.sources.registry import get_source


_NON_FACT_METRICS = {
    "date",
    "phone no",
    "phone number",
    "posted on",
    "release id",
    "scrip code",
    "visitor counter",
}
_MONTH_HEADING_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4}\b",
    re.IGNORECASE,
)
_TIME_TOKEN_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


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

    letters = "".join(char for char in metric if char.isalpha())
    if len(letters) <= 2:
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

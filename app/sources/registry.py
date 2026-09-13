from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class AuthorityLevel(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    category: str
    authority_level: AuthorityLevel
    country: str | None = None
    requires_license: bool = False
    enabled: bool = True
    independence_group: str | None = None


TRUSTED_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        source_id="rbi",
        name="Reserve Bank of India",
        base_url="https://www.rbi.org.in/",
        allowed_hosts=(
            "www.rbi.org.in",
            "rbi.org.in",
            "website.rbi.org.in",
            "m.rbi.org.in",
            "rbidocs.rbi.org.in",
            "bulletin.rbi.org.in",
        ),
        category="central_bank",
        authority_level=AuthorityLevel.A,
        country="IN",
        independence_group="rbi",
    ),
    SourceDefinition(
        source_id="sebi",
        name="Securities and Exchange Board of India",
        base_url="https://www.sebi.gov.in/",
        allowed_hosts=("www.sebi.gov.in", "sebi.gov.in"),
        category="regulator",
        authority_level=AuthorityLevel.A,
        country="IN",
        independence_group="sebi",
    ),
    SourceDefinition(
        source_id="nse",
        name="National Stock Exchange of India",
        base_url="https://www.nseindia.com/",
        allowed_hosts=("www.nseindia.com", "nseindia.com", "archives.nseindia.com", "nsearchives.nseindia.com"),
        category="exchange",
        authority_level=AuthorityLevel.A,
        country="IN",
        independence_group="nse",
    ),
    SourceDefinition(
        source_id="mospi",
        name="Ministry of Statistics and Programme Implementation",
        base_url="https://www.mospi.gov.in/",
        allowed_hosts=("www.mospi.gov.in", "mospi.gov.in", "esankhyiki.mospi.gov.in"),
        category="government_statistics",
        authority_level=AuthorityLevel.A,
        country="IN",
        independence_group="mospi",
    ),
    SourceDefinition(
        source_id="world_bank",
        name="World Bank",
        base_url="https://www.worldbank.org/",
        allowed_hosts=(
            "www.worldbank.org",
            "worldbank.org",
            "api.worldbank.org",
            "documents1.worldbank.org",
        ),
        category="international_organization",
        authority_level=AuthorityLevel.B,
        independence_group="world_bank",
    ),
    SourceDefinition(
        source_id="imf",
        name="International Monetary Fund",
        base_url="https://www.imf.org/",
        allowed_hosts=("www.imf.org", "imf.org"),
        category="international_organization",
        authority_level=AuthorityLevel.B,
        independence_group="imf",
    ),
    SourceDefinition(
        source_id="ddnews",
        name="DD News",
        base_url="https://ddnews.gov.in/",
        allowed_hosts=("ddnews.gov.in", "www.ddnews.gov.in"),
        category="government_public_broadcaster",
        authority_level=AuthorityLevel.B,
        country="IN",
        independence_group="prasar_bharati",
    ),
    SourceDefinition(
        source_id="akashvani",
        name="Akashvani News",
        base_url="https://newsonair.gov.in/",
        allowed_hosts=("newsonair.gov.in", "www.newsonair.gov.in"),
        category="government_public_broadcaster",
        authority_level=AuthorityLevel.B,
        country="IN",
        independence_group="prasar_bharati",
    ),
)


def get_source(source_id: str) -> SourceDefinition:
    for source in TRUSTED_SOURCES:
        if source.source_id == source_id and source.enabled:
            return source
    raise ValueError(f"Unknown or disabled source: {source_id}")


def get_source_independence_group(source_id: str) -> str:
    """Return the organization-level independence group for one source.

    Different websites or brands owned by the same publisher must not be counted
    as independent corroboration. Unknown synthetic/test sources safely fall back
    to their own source ID in the verification layer rather than being merged.
    """
    source = get_source(source_id)
    return source.independence_group or source.source_id


def validate_source_url(source_id: str, url: str) -> SourceDefinition:
    source = get_source(source_id)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError("Only HTTPS source URLs are allowed")
    if host not in source.allowed_hosts:
        raise ValueError(f"URL host {host!r} is not allow-listed for source {source_id!r}")
    return source

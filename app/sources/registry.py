from dataclasses import dataclass
from enum import StrEnum


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
    category: str
    authority_level: AuthorityLevel
    country: str | None = None
    requires_license: bool = False
    enabled: bool = True


TRUSTED_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        source_id="rbi",
        name="Reserve Bank of India",
        base_url="https://www.rbi.org.in/",
        category="central_bank",
        authority_level=AuthorityLevel.A,
        country="IN",
    ),
    SourceDefinition(
        source_id="sebi",
        name="Securities and Exchange Board of India",
        base_url="https://www.sebi.gov.in/",
        category="regulator",
        authority_level=AuthorityLevel.A,
        country="IN",
    ),
    SourceDefinition(
        source_id="nse",
        name="National Stock Exchange of India",
        base_url="https://www.nseindia.com/",
        category="exchange",
        authority_level=AuthorityLevel.A,
        country="IN",
    ),
    SourceDefinition(
        source_id="mospi",
        name="Ministry of Statistics and Programme Implementation",
        base_url="https://www.mospi.gov.in/",
        category="government_statistics",
        authority_level=AuthorityLevel.A,
        country="IN",
    ),
    SourceDefinition(
        source_id="world_bank",
        name="World Bank",
        base_url="https://www.worldbank.org/",
        category="international_organization",
        authority_level=AuthorityLevel.B,
    ),
    SourceDefinition(
        source_id="imf",
        name="International Monetary Fund",
        base_url="https://www.imf.org/",
        category="international_organization",
        authority_level=AuthorityLevel.B,
    ),
)

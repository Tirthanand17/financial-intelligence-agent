from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from app.sources.registry import validate_source_url


WORLD_BANK_INDICATORS_API_BASE = "https://api.worldbank.org/v2"
WORLD_BANK_DEFAULT_COUNTRY = "IND"
_WORLD_BANK_ALLOWED_COUNTRIES = frozenset({WORLD_BANK_DEFAULT_COUNTRY})
_MAX_RECENT_OBSERVATIONS = 5
_ANNUAL_PERIOD_RE = re.compile(r"^\d{4}$")


@dataclass(frozen=True, slots=True)
class WorldBankIndicatorSpec:
    code: str
    canonical_metric: str
    expected_unit: str


# Candidate coverage is deliberately small and exact. Expanding these codes is a
# source-policy decision, not something callers can do through arbitrary input.
WORLD_BANK_INDICATOR_SPECS: dict[str, WorldBankIndicatorSpec] = {
    "NY.GDP.MKTP.KD.ZG": WorldBankIndicatorSpec(
        code="NY.GDP.MKTP.KD.ZG",
        canonical_metric="Real GDP Growth",
        expected_unit="%",
    ),
    "FP.CPI.TOTL.ZG": WorldBankIndicatorSpec(
        code="FP.CPI.TOTL.ZG",
        canonical_metric="CPI Inflation",
        expected_unit="%",
    ),
    "SL.UEM.TOTL.ZS": WorldBankIndicatorSpec(
        code="SL.UEM.TOTL.ZS",
        canonical_metric="Unemployment Rate",
        expected_unit="%",
    ),
}


@dataclass(frozen=True, slots=True)
class WorldBankObservation:
    indicator_code: str
    indicator_name: str
    canonical_metric: str
    country_code: str
    country_name: str
    observation_period: str
    value_numeric: Decimal | None
    source_unit: str | None
    expected_unit: str
    observation_status: str | None
    source_last_updated: date | None
    publication_date: None = None
    effective_date: None = None

    @property
    def is_forecast(self) -> bool:
        return (self.observation_status or "").strip().upper() == "F"

    @property
    def eligible_for_fact(self) -> bool:
        # Missing values and explicitly forecast observations are retained for
        # diagnostics but are never eligible to become current factual claims.
        return self.value_numeric is not None and not self.is_forecast


@dataclass(frozen=True, slots=True)
class WorldBankParsedPayload:
    raw_content: bytes
    requested_indicator_code: str
    requested_country_code: str
    source_last_updated: date | None
    observations: tuple[WorldBankObservation, ...]


def build_world_bank_indicator_url(
    indicator_code: str,
    *,
    country_code: str = WORLD_BANK_DEFAULT_COUNTRY,
    recent_observations: int = 3,
) -> str:
    """Build one bounded allow-listed World Bank Indicators API request.

    The candidate adapter intentionally supports only India and an exact set of
    macro indicators while rollout observation is still open. It accepts no
    arbitrary base URL, host, path, or query string.
    """
    if indicator_code not in WORLD_BANK_INDICATOR_SPECS:
        raise ValueError("Unsupported World Bank indicator code")
    if country_code not in _WORLD_BANK_ALLOWED_COUNTRIES:
        raise ValueError("Unsupported World Bank country code")
    if not 1 <= recent_observations <= _MAX_RECENT_OBSERVATIONS:
        raise ValueError("recent_observations must be between 1 and 5")

    query = urlencode(
        {
            "format": "json",
            "mrv": recent_observations,
            "per_page": recent_observations,
        }
    )
    url = (
        f"{WORLD_BANK_INDICATORS_API_BASE}/country/{country_code}/indicator/"
        f"{indicator_code}?{query}"
    )
    validate_source_url("world_bank", url)
    return url


def _parse_iso_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("World Bank lastupdated must be an ISO date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("Invalid World Bank lastupdated date") from exc


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("World Bank observation value cannot be boolean")
    if not isinstance(value, (int, float, str)):
        raise ValueError("Unsupported World Bank observation value type")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid World Bank observation value") from exc


def _string_field(value: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"World Bank {field} must be a string")
    cleaned = " ".join(value.split()).strip()
    if not cleaned and not allow_empty:
        raise ValueError(f"World Bank {field} is empty")
    return cleaned


def parse_world_bank_indicator_payload(
    content: bytes,
    *,
    expected_indicator_code: str,
    expected_country_code: str = WORLD_BANK_DEFAULT_COUNTRY,
    max_observations: int = _MAX_RECENT_OBSERVATIONS,
) -> WorldBankParsedPayload:
    """Parse exact World Bank JSON bytes without inventing temporal metadata.

    World Bank `date` is retained as an observation period. It is deliberately
    NOT mapped into this project's publication_date/effective_date fields.
    Response-level `lastupdated` is retained separately as source metadata and is
    also not treated as a claim publication/effective date.
    """
    if expected_indicator_code not in WORLD_BANK_INDICATOR_SPECS:
        raise ValueError("Unsupported World Bank indicator code")
    if expected_country_code not in _WORLD_BANK_ALLOWED_COUNTRIES:
        raise ValueError("Unsupported World Bank country code")
    if not 1 <= max_observations <= _MAX_RECENT_OBSERVATIONS:
        raise ValueError("max_observations must be between 1 and 5")

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid World Bank API JSON") from exc

    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("Unexpected World Bank API response shape")
    metadata, rows = payload
    if not isinstance(metadata, dict) or not isinstance(rows, list):
        raise ValueError("Unexpected World Bank API response shape")
    if len(rows) > max_observations:
        raise ValueError("World Bank response exceeded bounded observation limit")

    source_last_updated = _parse_iso_date(metadata.get("lastupdated"))
    spec = WORLD_BANK_INDICATOR_SPECS[expected_indicator_code]
    observations: list[WorldBankObservation] = []

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Unexpected World Bank observation record")

        indicator = row.get("indicator")
        country = row.get("country")
        if not isinstance(indicator, dict) or not isinstance(country, dict):
            raise ValueError("World Bank observation is missing indicator/country metadata")

        indicator_code = _string_field(indicator.get("id"), field="indicator.id")
        if indicator_code != expected_indicator_code:
            raise ValueError("World Bank response indicator does not match request")
        indicator_name = _string_field(indicator.get("value"), field="indicator.value")

        country_code = _string_field(row.get("countryiso3code"), field="countryiso3code")
        if country_code != expected_country_code:
            raise ValueError("World Bank response country does not match request")
        country_name = _string_field(country.get("value"), field="country.value")

        observation_period = _string_field(row.get("date"), field="date")
        # The initial adapter accepts annual periods only. Monthly/quarterly data
        # requires a separately reviewed temporal contract before activation.
        if _ANNUAL_PERIOD_RE.fullmatch(observation_period) is None:
            raise ValueError("Unsupported World Bank observation period")

        source_unit_value = row.get("unit")
        source_unit = None
        if source_unit_value not in (None, ""):
            source_unit = _string_field(source_unit_value, field="unit")

        status_value = row.get("obs_status")
        observation_status = None
        if status_value not in (None, ""):
            observation_status = _string_field(status_value, field="obs_status")

        observations.append(
            WorldBankObservation(
                indicator_code=indicator_code,
                indicator_name=indicator_name,
                canonical_metric=spec.canonical_metric,
                country_code=country_code,
                country_name=country_name,
                observation_period=observation_period,
                value_numeric=_decimal_or_none(row.get("value")),
                source_unit=source_unit,
                expected_unit=spec.expected_unit,
                observation_status=observation_status,
                source_last_updated=source_last_updated,
            )
        )

    return WorldBankParsedPayload(
        raw_content=content,
        requested_indicator_code=expected_indicator_code,
        requested_country_code=expected_country_code,
        source_last_updated=source_last_updated,
        observations=tuple(observations),
    )

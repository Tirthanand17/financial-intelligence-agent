from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


IMF_CPI_DATAFLOW_ID = "CPI"
IMF_CPI_DATAFLOW_VERSION = "1.0"
IMF_CPI_DSD_ID = "ECOFIN_DSD"
IMF_CPI_DSD_VERSION = "1.0"
IMF_CPI_DATA_DOMAIN = "CPI"
IMF_CPI_INDIA_REF_AREA = "IN"
IMF_CPI_ALL_ITEMS_INDICATOR = "PCPI_IX"
IMF_CPI_NO_COUNTERPART_AREA = "_Z"
IMF_CPI_CANONICAL_METRIC = "Consumer Price Index, All items"
IMF_CPI_EXPECTED_UNIT = "index"
IMF_CPI_MAX_OBSERVATIONS = 12

_REQUIRED_COLUMNS = frozenset(
    {
        "DATA_DOMAIN",
        "REF_AREA",
        "INDICATOR",
        "COUNTERPART_AREA",
        "FREQ",
        "TIME_PERIOD",
        "OBS_VALUE",
    }
)
_ANNUAL_PERIOD_RE = re.compile(r"^\d{4}$")
_QUARTERLY_PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")
_MONTHLY_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_ALLOWED_FREQUENCIES = frozenset({"A", "Q", "M"})


@dataclass(frozen=True, slots=True)
class ImfCpiObservation:
    frequency: str
    ref_area: str
    indicator_code: str
    observation_period: str
    value_numeric: Decimal | None
    observation_status: str | None
    base_period: str | None
    unit_multiplier: str | None
    counterpart_area: str
    publication_date: None = None
    effective_date: None = None

    @property
    def is_forecast(self) -> bool:
        return (self.observation_status or "").strip().upper() == "F"

    @property
    def eligible_for_fact(self) -> bool:
        # The candidate adapter deliberately does not create structured claims.
        # Observation periods are not publication/effective dates, and forecast
        # observations must never be treated as current factual evidence.
        return self.value_numeric is not None and not self.is_forecast


@dataclass(frozen=True, slots=True)
class ImfCpiParsedPayload:
    raw_content: bytes
    dataflow_id: str
    dataflow_version: str
    data_structure_id: str
    data_structure_version: str
    data_domain: str
    requested_ref_area: str
    requested_indicator_code: str
    counterpart_area: str
    observations: tuple[ImfCpiObservation, ...]


def _clean_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"IMF CPI {field} must be a string")
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        raise ValueError(f"IMF CPI {field} is empty")
    return cleaned


def _optional_text(value: object, *, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _clean_text(value, field=field)


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("IMF CPI OBS_VALUE must be text")
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid IMF CPI OBS_VALUE") from exc


def _validate_period(frequency: str, period: str) -> None:
    matcher = {
        "A": _ANNUAL_PERIOD_RE,
        "Q": _QUARTERLY_PERIOD_RE,
        "M": _MONTHLY_PERIOD_RE,
    }[frequency]
    if matcher.fullmatch(period) is None:
        raise ValueError("IMF CPI TIME_PERIOD does not match FREQ")


def parse_imf_cpi_sdmx_csv(
    content: bytes,
    *,
    expected_ref_area: str = IMF_CPI_INDIA_REF_AREA,
    expected_indicator_code: str = IMF_CPI_ALL_ITEMS_INDICATOR,
    max_observations: int = IMF_CPI_MAX_OBSERVATIONS,
) -> ImfCpiParsedPayload:
    """Parse bounded IMF CPI SDMX-CSV bytes without inventing temporal facts.

    The public IMF registry contract validated on 20 September 2026 identifies
    dataflow IMF:CPI(1.0), DSD IMF:ECOFIN_DSD(1.0), domain CPI, India as IN,
    all-items CPI as PCPI_IX, and no-counterpart as _Z. The authenticated IMF
    Data API endpoint remains separately gated and is not inferred here.
    """
    expected_ref_area = _clean_text(expected_ref_area, field="expected_ref_area").upper()
    if expected_ref_area != IMF_CPI_INDIA_REF_AREA:
        raise ValueError("Unsupported IMF CPI reference area")
    if expected_indicator_code != IMF_CPI_ALL_ITEMS_INDICATOR:
        raise ValueError("Unsupported IMF CPI indicator code")
    if not 1 <= max_observations <= IMF_CPI_MAX_OBSERVATIONS:
        raise ValueError("max_observations must be between 1 and 12")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("IMF CPI SDMX-CSV must be UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = tuple(reader.fieldnames or ())
    if not fieldnames:
        raise ValueError("IMF CPI SDMX-CSV is missing a header")
    missing = _REQUIRED_COLUMNS.difference(fieldnames)
    if missing:
        raise ValueError(
            "IMF CPI SDMX-CSV is missing required columns: " + ", ".join(sorted(missing))
        )

    observations: list[ImfCpiObservation] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in reader:
        if row is None or not any((value or "").strip() for value in row.values() if isinstance(value, str)):
            continue
        if len(observations) >= max_observations:
            raise ValueError("IMF CPI response exceeded bounded observation limit")

        data_domain = _clean_text(row.get("DATA_DOMAIN"), field="DATA_DOMAIN")
        if data_domain != IMF_CPI_DATA_DOMAIN:
            raise ValueError("IMF CPI response data domain does not match CPI contract")

        frequency = _clean_text(row.get("FREQ"), field="FREQ").upper()
        if frequency not in _ALLOWED_FREQUENCIES:
            raise ValueError("Unsupported IMF CPI frequency")

        ref_area = _clean_text(row.get("REF_AREA"), field="REF_AREA").upper()
        if ref_area != expected_ref_area:
            raise ValueError("IMF CPI response reference area does not match request")

        indicator_code = _clean_text(row.get("INDICATOR"), field="INDICATOR")
        if indicator_code != expected_indicator_code:
            raise ValueError("IMF CPI response indicator does not match request")

        counterpart_area = _clean_text(row.get("COUNTERPART_AREA"), field="COUNTERPART_AREA")
        if counterpart_area != IMF_CPI_NO_COUNTERPART_AREA:
            raise ValueError("IMF CPI response counterpart area does not match CPI contract")

        observation_period = _clean_text(row.get("TIME_PERIOD"), field="TIME_PERIOD")
        _validate_period(frequency, observation_period)

        observation_status = _optional_text(row.get("OBS_STATUS"), field="OBS_STATUS")
        base_period = _optional_text(row.get("BASE_PER"), field="BASE_PER")
        unit_multiplier = _optional_text(row.get("UNIT_MULT"), field="UNIT_MULT")

        key = (
            frequency,
            ref_area,
            indicator_code,
            observation_period,
            counterpart_area,
        )
        if key in seen:
            raise ValueError("Duplicate IMF CPI observation key")
        seen.add(key)

        observations.append(
            ImfCpiObservation(
                frequency=frequency,
                ref_area=ref_area,
                indicator_code=indicator_code,
                observation_period=observation_period,
                value_numeric=_decimal_or_none(row.get("OBS_VALUE")),
                observation_status=observation_status,
                base_period=base_period,
                unit_multiplier=unit_multiplier,
                counterpart_area=counterpart_area,
            )
        )

    if not observations:
        raise ValueError("IMF CPI payload contains no observations")

    return ImfCpiParsedPayload(
        raw_content=content,
        dataflow_id=IMF_CPI_DATAFLOW_ID,
        dataflow_version=IMF_CPI_DATAFLOW_VERSION,
        data_structure_id=IMF_CPI_DSD_ID,
        data_structure_version=IMF_CPI_DSD_VERSION,
        data_domain=IMF_CPI_DATA_DOMAIN,
        requested_ref_area=expected_ref_area,
        requested_indicator_code=expected_indicator_code,
        counterpart_area=IMF_CPI_NO_COUNTERPART_AREA,
        observations=tuple(observations),
    )

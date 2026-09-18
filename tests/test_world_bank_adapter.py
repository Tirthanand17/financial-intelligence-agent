import json
from decimal import Decimal

import pytest

from app.sources.world_bank import (
    WORLD_BANK_INDICATOR_SPECS,
    build_world_bank_indicator_url,
    parse_world_bank_indicator_payload,
)


def _payload(*, rows: list[dict[str, object]], lastupdated: str = "2026-09-17") -> bytes:
    return json.dumps(
        [
            {
                "page": 1,
                "pages": 1,
                "per_page": len(rows),
                "total": len(rows),
                "lastupdated": lastupdated,
            },
            rows,
        ]
    ).encode("utf-8")


def _row(
    *,
    indicator: str = "NY.GDP.MKTP.KD.ZG",
    date: str = "2025",
    value: object = 6.5,
    country: str = "IND",
    obs_status: str = "",
) -> dict[str, object]:
    return {
        "indicator": {"id": indicator, "value": "GDP growth (annual %)"},
        "country": {"id": "IN", "value": "India"},
        "countryiso3code": country,
        "date": date,
        "value": value,
        "unit": "",
        "obs_status": obs_status,
        "decimal": 1,
    }


def test_world_bank_query_is_bounded_to_allowlisted_country_indicator_and_host() -> None:
    url = build_world_bank_indicator_url(
        "NY.GDP.MKTP.KD.ZG",
        recent_observations=3,
    )

    assert url.startswith(
        "https://api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.KD.ZG?"
    )
    assert "format=json" in url
    assert "mrv=3" in url
    assert "per_page=3" in url

    with pytest.raises(ValueError):
        build_world_bank_indicator_url("ARBITRARY.CODE")
    with pytest.raises(ValueError):
        build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", country_code="USA")
    with pytest.raises(ValueError):
        build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", recent_observations=6)

    assert set(WORLD_BANK_INDICATOR_SPECS) == {
        "NY.GDP.MKTP.KD.ZG",
        "FP.CPI.TOTL.ZG",
        "SL.UEM.TOTL.ZS",
    }


def test_world_bank_parser_preserves_observation_period_without_inventing_claim_dates() -> None:
    content = _payload(rows=[_row(date="2025", value=6.5), _row(date="2024", value=6.1)])
    result = parse_world_bank_indicator_payload(
        content,
        expected_indicator_code="NY.GDP.MKTP.KD.ZG",
        max_observations=2,
    )

    assert result.raw_content == content
    assert result.source_last_updated.isoformat() == "2026-09-17"
    assert len(result.observations) == 2

    newest = result.observations[0]
    assert newest.indicator_code == "NY.GDP.MKTP.KD.ZG"
    assert newest.canonical_metric == "Real GDP Growth"
    assert newest.country_code == "IND"
    assert newest.observation_period == "2025"
    assert newest.value_numeric == Decimal("6.5")
    assert newest.expected_unit == "%"
    assert newest.publication_date is None
    assert newest.effective_date is None
    assert newest.is_forecast is False
    assert newest.eligible_for_fact is True


def test_world_bank_parser_retains_but_disqualifies_forecast_and_missing_values() -> None:
    result = parse_world_bank_indicator_payload(
        _payload(
            rows=[
                _row(date="2025", value=6.5, obs_status="F"),
                _row(date="2024", value=None),
            ]
        ),
        expected_indicator_code="NY.GDP.MKTP.KD.ZG",
        max_observations=2,
    )

    forecast, missing = result.observations
    assert forecast.is_forecast is True
    assert forecast.eligible_for_fact is False
    assert missing.value_numeric is None
    assert missing.eligible_for_fact is False


def test_world_bank_parser_fails_closed_on_scope_or_temporal_mismatch() -> None:
    with pytest.raises(ValueError, match="indicator"):
        parse_world_bank_indicator_payload(
            _payload(rows=[_row(indicator="FP.CPI.TOTL.ZG")]),
            expected_indicator_code="NY.GDP.MKTP.KD.ZG",
        )

    with pytest.raises(ValueError, match="country"):
        parse_world_bank_indicator_payload(
            _payload(rows=[_row(country="USA")]),
            expected_indicator_code="NY.GDP.MKTP.KD.ZG",
        )

    with pytest.raises(ValueError, match="observation period"):
        parse_world_bank_indicator_payload(
            _payload(rows=[_row(date="2025Q1")]),
            expected_indicator_code="NY.GDP.MKTP.KD.ZG",
        )

    with pytest.raises(ValueError, match="bounded observation limit"):
        parse_world_bank_indicator_payload(
            _payload(rows=[_row(date="2025"), _row(date="2024")]),
            expected_indicator_code="NY.GDP.MKTP.KD.ZG",
            max_observations=1,
        )

    with pytest.raises(ValueError, match="Invalid World Bank API JSON"):
        parse_world_bank_indicator_payload(
            b"not-json",
            expected_indicator_code="NY.GDP.MKTP.KD.ZG",
        )

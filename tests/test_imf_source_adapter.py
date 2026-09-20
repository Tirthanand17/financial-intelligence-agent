from decimal import Decimal

import pytest

from app.sources.imf import (
    IMF_CPI_ALL_ITEMS_INDICATOR,
    IMF_CPI_DATAFLOW_ID,
    IMF_CPI_DATAFLOW_VERSION,
    parse_imf_cpi_sdmx_csv,
)


def _payload(*rows: str) -> bytes:
    header = (
        "FREQ,REF_AREA,INDICATOR,COUNTERPART_AREA,TIME_PERIOD,OBS_VALUE,"
        "OBS_STATUS,BASE_PER,UNIT_MULT\n"
    )
    return (header + "\n".join(rows) + "\n").encode("utf-8")


def test_parses_bounded_cpi_rows_without_inventing_dates() -> None:
    content = _payload(
        "M,IND,PCPI_IX,,2026-05,123.4,,2012=100,0",
        "M,IND,PCPI_IX,,2026-06,124.1,P,2012=100,0",
    )

    parsed = parse_imf_cpi_sdmx_csv(content, expected_ref_area="IND")

    assert parsed.raw_content == content
    assert parsed.dataflow_id == IMF_CPI_DATAFLOW_ID
    assert parsed.dataflow_version == IMF_CPI_DATAFLOW_VERSION
    assert parsed.requested_ref_area == "IND"
    assert parsed.requested_indicator_code == IMF_CPI_ALL_ITEMS_INDICATOR
    assert len(parsed.observations) == 2

    first, second = parsed.observations
    assert first.observation_period == "2026-05"
    assert first.value_numeric == Decimal("123.4")
    assert first.publication_date is None
    assert first.effective_date is None
    assert first.eligible_for_fact is True
    assert second.observation_status == "P"
    assert second.publication_date is None
    assert second.effective_date is None


def test_forecast_status_is_retained_but_not_fact_eligible() -> None:
    parsed = parse_imf_cpi_sdmx_csv(
        _payload("A,IND,PCPI_IX,,2026,125.0,F,2012=100,0"),
        expected_ref_area="IND",
    )

    observation = parsed.observations[0]
    assert observation.is_forecast is True
    assert observation.eligible_for_fact is False
    assert observation.publication_date is None
    assert observation.effective_date is None


def test_missing_value_is_retained_but_not_fact_eligible() -> None:
    parsed = parse_imf_cpi_sdmx_csv(
        _payload("Q,IND,PCPI_IX,,2026-Q2,,,2012=100,0"),
        expected_ref_area="IND",
    )
    assert parsed.observations[0].value_numeric is None
    assert parsed.observations[0].eligible_for_fact is False


@pytest.mark.parametrize(
    ("frequency", "period"),
    [
        ("A", "2026-01"),
        ("Q", "2026-Q5"),
        ("M", "2026-13"),
        ("W", "2026-W20"),
    ],
)
def test_rejects_frequency_period_contract_mismatch(frequency: str, period: str) -> None:
    with pytest.raises(ValueError):
        parse_imf_cpi_sdmx_csv(
            _payload(f"{frequency},IND,PCPI_IX,,{period},100,,2012=100,0"),
            expected_ref_area="IND",
        )


def test_rejects_wrong_area_indicator_and_duplicates() -> None:
    with pytest.raises(ValueError, match="reference area"):
        parse_imf_cpi_sdmx_csv(
            _payload("M,USA,PCPI_IX,,2026-01,100,,2012=100,0"),
            expected_ref_area="IND",
        )

    with pytest.raises(ValueError, match="indicator"):
        parse_imf_cpi_sdmx_csv(
            _payload("M,IND,OTHER,,2026-01,100,,2012=100,0"),
            expected_ref_area="IND",
        )

    duplicate = _payload(
        "M,IND,PCPI_IX,,2026-01,100,,2012=100,0",
        "M,IND,PCPI_IX,,2026-01,101,R,2012=100,0",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        parse_imf_cpi_sdmx_csv(duplicate, expected_ref_area="IND")


def test_rejects_unbounded_rows_and_missing_required_columns() -> None:
    rows = [f"M,IND,PCPI_IX,,2026-{month:02d},{100 + month},,2012=100,0" for month in range(1, 4)]
    with pytest.raises(ValueError, match="bounded observation limit"):
        parse_imf_cpi_sdmx_csv(
            _payload(*rows),
            expected_ref_area="IND",
            max_observations=2,
        )

    with pytest.raises(ValueError, match="required columns"):
        parse_imf_cpi_sdmx_csv(
            b"FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\nM,IND,2026-01,100\n",
            expected_ref_area="IND",
        )

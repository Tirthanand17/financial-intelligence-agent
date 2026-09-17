from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    indicator_id: str
    canonical_metric: str
    category: str
    aliases: tuple[str, ...]
    expected_units: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class IndicatorResolution:
    source_metric: str
    canonical_metric: str
    indicator_id: str | None
    category: str | None
    expected_units: tuple[str, ...]
    basis: str


def _metric_key(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    cleaned = cleaned.rstrip(".:;")
    return cleaned.casefold()


INDICATOR_DEFINITIONS: tuple[IndicatorDefinition, ...] = (
    IndicatorDefinition(
        indicator_id="policy_repo_rate",
        canonical_metric="Policy Repo Rate",
        category="monetary_policy",
        aliases=("Policy Repo Rate", "Repo Rate"),
        expected_units=("%",),
        description="Policy repo rate published by the monetary authority.",
    ),
    IndicatorDefinition(
        indicator_id="standing_deposit_facility_rate",
        canonical_metric="Standing Deposit Facility Rate",
        category="monetary_policy",
        aliases=("Standing Deposit Facility Rate", "SDF Rate"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="marginal_standing_facility_rate",
        canonical_metric="Marginal Standing Facility Rate",
        category="monetary_policy",
        aliases=("Marginal Standing Facility Rate", "MSF Rate"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="bank_rate",
        canonical_metric="Bank Rate",
        category="monetary_policy",
        aliases=("Bank Rate",),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="cash_reserve_ratio",
        canonical_metric="Cash Reserve Ratio",
        category="monetary_policy",
        aliases=("Cash Reserve Ratio", "CRR"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="statutory_liquidity_ratio",
        canonical_metric="Statutory Liquidity Ratio",
        category="monetary_policy",
        aliases=("Statutory Liquidity Ratio", "SLR"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="cpi_inflation",
        canonical_metric="CPI Inflation",
        category="inflation",
        aliases=("CPI Inflation", "Consumer Price Index Inflation", "CPI Inflation Rate"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="wpi_inflation",
        canonical_metric="WPI Inflation",
        category="inflation",
        aliases=("WPI Inflation", "Wholesale Price Index Inflation", "WPI Inflation Rate"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="real_gdp_growth",
        canonical_metric="Real GDP Growth",
        category="national_accounts",
        aliases=(
            "Real GDP Growth",
            "Real GDP Growth Rate",
            "GDP Growth",
            "GDP Growth Rate",
            "Gross Domestic Product Growth Rate",
        ),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="iip_growth",
        canonical_metric="IIP Growth",
        category="industrial_activity",
        aliases=("IIP Growth", "IIP Growth Rate", "Index of Industrial Production Growth"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="unemployment_rate",
        canonical_metric="Unemployment Rate",
        category="labour_market",
        aliases=("Unemployment Rate",),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="labour_force_participation_rate",
        canonical_metric="Labour Force Participation Rate",
        category="labour_market",
        aliases=("Labour Force Participation Rate", "LFPR"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="worker_population_ratio",
        canonical_metric="Worker Population Ratio",
        category="labour_market",
        aliases=("Worker Population Ratio", "WPR"),
        expected_units=("%",),
    ),
    IndicatorDefinition(
        indicator_id="fiscal_deficit",
        canonical_metric="Fiscal Deficit",
        category="public_finance",
        aliases=("Fiscal Deficit",),
        expected_units=("INR", "crore", "%"),
    ),
    IndicatorDefinition(
        indicator_id="revenue_deficit",
        canonical_metric="Revenue Deficit",
        category="public_finance",
        aliases=("Revenue Deficit",),
        expected_units=("INR", "crore", "%"),
    ),
    IndicatorDefinition(
        indicator_id="foreign_exchange_reserves",
        canonical_metric="Foreign Exchange Reserves",
        category="external_sector",
        aliases=("Foreign Exchange Reserves", "Forex Reserves"),
        expected_units=("USD", "billion", "million"),
    ),
    IndicatorDefinition(
        indicator_id="current_account_balance",
        canonical_metric="Current Account Balance",
        category="external_sector",
        aliases=("Current Account Balance", "Current Account Deficit"),
        expected_units=("USD", "billion", "million", "%"),
    ),
)


def _build_alias_index() -> dict[str, IndicatorDefinition]:
    index: dict[str, IndicatorDefinition] = {}
    for definition in INDICATOR_DEFINITIONS:
        for label in (definition.canonical_metric, *definition.aliases):
            key = _metric_key(label)
            existing = index.get(key)
            if existing is not None and existing.indicator_id != definition.indicator_id:
                raise RuntimeError(
                    f"Indicator alias {label!r} is ambiguous between "
                    f"{existing.indicator_id!r} and {definition.indicator_id!r}"
                )
            index[key] = definition
    return index


_ALIAS_INDEX = _build_alias_index()


def normalize_indicator_metric(metric: str) -> IndicatorResolution:
    """Return a deterministic exact-alias normalization overlay.

    The persisted source metric is never rewritten by this function. Unknown
    labels stay unmapped rather than being guessed through fuzzy similarity.
    """
    source_metric = " ".join(metric.split()).strip()
    definition = _ALIAS_INDEX.get(_metric_key(source_metric))
    if definition is None:
        return IndicatorResolution(
            source_metric=source_metric,
            canonical_metric=source_metric,
            indicator_id=None,
            category=None,
            expected_units=(),
            basis="unmapped_exact",
        )
    return IndicatorResolution(
        source_metric=source_metric,
        canonical_metric=definition.canonical_metric,
        indicator_id=definition.indicator_id,
        category=definition.category,
        expected_units=definition.expected_units,
        basis="exact_catalog_alias",
    )


def catalog_definitions() -> tuple[IndicatorDefinition, ...]:
    return INDICATOR_DEFINITIONS

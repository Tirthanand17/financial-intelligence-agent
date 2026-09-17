# Economic Indicator Catalog & Metric Normalization

## Purpose

This post-roadmap milestone adds a conservative, read-only canonical indicator catalog on top of persisted structured claims. It improves navigation and comparison without rewriting historical evidence.

## Safety properties

- Persisted `claims.metric` values are never rewritten by the catalog.
- Unknown labels remain unmapped; fuzzy or semantic guessing is not used.
- Canonicalization requires an exact reviewed alias after whitespace/case normalization.
- No claim-state transition, verification event, trust event, ingestion, scheduler change, or evidence deletion occurs.
- Original source labels remain visible beside canonical labels.
- Unit expectations are diagnostics only; a unit mismatch does not silently alter the claim.

## Catalog scope

The initial catalog covers tightly scoped monetary-policy, inflation, national-accounts, industrial-activity, labour-market, public-finance, and external-sector indicators. Each definition has:

- stable `indicator_id`
- canonical metric label
- category
- reviewed exact aliases
- expected units where useful
- optional description

The catalog can grow only by review. Adding an alias is a code change with tests, not a runtime fuzzy-learning action.

## Read-only service

`app/services/indicator_catalog.py` overlays catalog resolution on persisted claims and reports:

- mapped vs unmapped claim counts
- observed vs unobserved indicators
- per-indicator source coverage
- observed units
- latest persisted observation
- original source metric alongside canonical metric
- unmapped labels requiring future review

## Protected dashboard

- `GET /dashboard/indicator-catalog`
- `GET /dashboard/indicator-catalog/status?limit=100`

Both routes reuse the existing private dashboard authentication. The JSON response is `Cache-Control: no-store`.

## Non-goals

This milestone does not:

- infer values that are not present in source evidence
- convert units
- guess an indicator from a similar-looking label
- rewrite old claims
- automatically verify or trust claims
- create forecasts, scores, or trading signals

## Future integration

The catalog is intended to support later evidence search, change detection, timeline grouping, conflict investigation, and data-quality reporting while preserving exact source provenance.

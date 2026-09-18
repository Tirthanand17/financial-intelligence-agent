# Evidence Quality Scorecards

## Purpose

Evidence Quality Scorecards provide factual completeness/provenance dimensions for persisted claims without producing a composite truth score, ranking sources, or changing verification/trust state.

## Protected routes

- `GET /dashboard/quality-scorecards`
- `GET /dashboard/quality-scorecards/status`

Both reuse dashboard authentication/security headers. JSON is `Cache-Control: no-store`.

## Dimensions

For the bounded persisted claim set the view reports, overall and per source:

- existing claim-quality gate pass;
- persisted publication/effective temporal scope present;
- canonical entity-attribution provenance recorded;
- linked document row present;
- linked document SHA-256 present;
- private raw-evidence reference present;
- source present in the enabled trusted-source registry;
- deterministic exact-alias indicator-catalog mapping present.

The raw evidence object key is only checked internally for presence and is never returned.

## Interpretation

There is deliberately no composite numeric quality/truth score, source ranking, truth probability, or automatic verification/trust decision. Each dimension is displayed separately with present/missing counts and percentages.

Indicator catalog mapping is informational. A persisted official source metric that is not in the small exact-alias catalog is not automatically invalid or low quality.

## Safety bounds and invariants

- scans at most 20,000 claims per snapshot and fails closed above the bound;
- read-only;
- no object-store key exposure;
- no claim/document mutation;
- no trust promotion;
- no evidence deletion/repair;
- no network crawling;
- no scheduler/ingestion changes;
- no forecasting or trading behavior.

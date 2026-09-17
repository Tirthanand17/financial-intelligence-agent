# Evidence Timeline Explorer

## Purpose

The Evidence Timeline Explorer is a protected, read-only post-roadmap intelligence surface for inspecting how persisted structured claims change over time.

It does not fetch new source material, mutate claim state, promote trust, generate forecasts, or produce trading signals.

## Routes

- `GET /dashboard/timeline` — authenticated human-readable timeline UI.
- `GET /dashboard/timeline/status` — authenticated JSON snapshot used by the UI.

Both routes reuse the existing dashboard HTTP Basic authentication and inherit the dashboard security-header middleware.

## Timeline semantics

A series is grouped by canonical `(entity, metric, unit)` from persisted structured claims.

Timeline ordering uses only dates already persisted with evidence:

1. `effective_date` when present.
2. otherwise `publication_date` when present.
3. otherwise the claim is explicitly marked `undated`.

Retrieval time is never substituted for a missing publication/effective date.

## Evidence shown

Each point may include:

- claim ID;
- publication/effective date and the temporal basis used;
- source ID/name and original source URL;
- persisted value and unit;
- claim state;
- confidence;
- claim quality-gate result;
- supersession relationships;
- source-grounded evidence excerpt;
- persistence creation timestamp.

Inactive states such as `rejected` and `superseded` remain visible as historical evidence but are not selected as the latest active value.

## Filters and bounds

The UI can filter by entity, metric, and source. Returned data is bounded by:

- `series_limit`: 1–50;
- `points_per_series`: 1–100.

The service is deliberately read-only and bounded to avoid turning a dashboard request into an unbounded operational workload.

## Safety invariants

The explorer must preserve these project rules:

- no invented dates;
- no source crawling;
- no ingestion;
- no claim-state mutation;
- no trust-event creation;
- no automatic trust promotion;
- no evidence deletion or rewriting;
- no forecast or trading recommendation;
- no write controls in the dashboard.

## Validation

Regression tests cover chronological ordering, explicit undated handling, source/filter behavior, supersession visibility, read-only route authentication, and bounded query parameters. Full repository CI must pass before merge and Render deployment.

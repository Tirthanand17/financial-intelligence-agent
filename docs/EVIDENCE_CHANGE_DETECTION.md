# Evidence Change Detection

## Purpose

Evidence Change Detection is a protected, read-only post-roadmap intelligence surface that compares persisted dated claims and highlights factual changes between comparable observations. It does not forecast markets or create trading recommendations.

## Routes

- `GET /dashboard/changes` — authenticated human-readable change view.
- `GET /dashboard/changes/status` — authenticated bounded JSON snapshot.

Both reuse the private dashboard authentication and security-header middleware.

## Comparison contract

A comparison series is exact on:

- canonical entity;
- exact-alias indicator ID when the metric is mapped by the indicator catalog, otherwise exact persisted metric text;
- persisted unit.

Fuzzy metric matching is disabled.

Only persisted `effective_date` or `publication_date` can position a claim in time. Claims without either are excluded from comparison and reported as missing temporal scope. Retrieval timestamps are never substituted.

Quality-failed and rejected derived claims are excluded. Superseded claims remain available because they are historical evidence and can participate in an explicit old-to-new supersession relationship.

## Change kinds

The service can surface:

- `numeric_value_change` — comparable numeric values with the same unit changed;
- `value_text_change` — comparable persisted textual values changed where a numeric delta is unavailable;
- `source_supersession` — a recorded supersession edge connects old and new evidence and the value changed;
- `supersession_same_value` — a recorded supersession edge replaced evidence while retaining the same observed value.

Direction (`increase` / `decrease`) and numeric delta are emitted only when both observations contain comparable numeric values with the same unit.

## Non-events

Repeated comparable evidence with the same observed value and no explicit supersession is counted as an unchanged confirmation rather than displayed as a change.

## Safety

The feature performs no writes and does not:

- mutate claim states;
- create verification/trust events;
- enable trust promotion;
- fetch or ingest sources;
- change scheduler cadence;
- rewrite or delete evidence;
- invent dates;
- use fuzzy matching;
- forecast markets;
- generate buy/sell instructions.

## Validation

Regression tests verify numeric change/direction, unchanged confirmations, superseded historical evidence, missing-date/quality/rejected exclusion, source filtering, authentication, and read-only HTTP behavior. Full repository CI must pass before merge.

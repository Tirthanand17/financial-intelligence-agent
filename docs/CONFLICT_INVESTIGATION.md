# Conflict Investigation View

## Purpose

The Conflict Investigation view is a protected, read-only inspection surface for independently published persisted claims that disagree in the same exact comparison scope. It does not resolve which value is correct and does not change the claim lifecycle.

## Protected routes

- `GET /dashboard/conflicts`
- `GET /dashboard/conflicts/status`

Both reuse the existing dashboard authentication and security-header middleware. JSON is explicitly `Cache-Control: no-store`.

## Comparison contract

A claim can participate only when it is active, passes the existing claim-quality gate, and has persisted temporal scope. Comparable claims must match on:

1. canonical entity after deterministic whitespace/case normalization;
2. metric identity using the existing exact-alias indicator catalog when mapped, otherwise the exact normalized persisted source metric;
3. exact normalized unit;
4. temporal kind and date, using `effective_date` when present and otherwise `publication_date`.

No fuzzy matching is used and retrieval time is never substituted for a publication/effective date.

A displayed conflict additionally requires:

- at least two publisher-independence groups; and
- at least two distinct persisted values.

Sibling brands/sites in one publisher group therefore cannot manufacture independent corroboration or conflict.

## What the view shows

For each conflict group it shows:

- entity, source metric and canonical indicator overlay;
- exact unit and persisted temporal scope;
- each distinct value;
- participating source IDs and publisher-independence groups;
- source authority level;
- claim state and confidence;
- publication/effective dates;
- source evidence excerpt and source URL;
- linked document title, SHA-256 and document status when available.

## Safety bounds

The service scans at most 20,000 active claims in one request. If that bound would be exceeded it fails closed and asks the operator to narrow the investigation instead of silently truncating evidence. Returned conflict groups are limited to 1–100.

## Non-negotiable behavior

- read-only;
- no source crawling;
- no fuzzy metric/entity matching;
- no invented dates;
- no claim-state transition;
- no verification/trust event creation;
- no automatic conflict resolution;
- no trust promotion;
- no evidence deletion, rewriting or repair;
- no scheduler or ingestion change;
- no forecast, ranking, trading signal or execution.

The view reports that a disagreement exists; it never declares a winning source or value.

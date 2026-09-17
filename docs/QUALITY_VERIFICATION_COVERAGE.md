# Claim Quality & Verification Coverage

This post-roadmap milestone adds a protected read-only view of two operational questions that remain important as the evidence corpus grows:

1. how much structured-claim noise is being blocked by the established Phase 16 quality floor; and
2. how much independent publisher coverage exists for exact verification comparison groups.

## Exact comparison dimensions

The coverage inventory groups quality-safe, active claims only when all persisted dimensions match exactly:

- canonical entity text;
- metric text;
- unit;
- temporal kind (`effective` preferred, otherwise `publication`);
- exact persisted temporal date.

No fuzzy matching, guessed dates, inferred entity relationships, or AI-generated normalization is introduced here. Claims without explicit temporal scope are reported separately rather than being force-matched.

## Publisher independence

Source IDs are converted through the existing source-registry independence-group policy. Multiple brands or sites from the same publisher group therefore count once, preserving the existing verification boundary.

Each exact comparison group is classified as:

- `single_independence_group` — not enough independent evidence yet;
- `independently_supported_same_value` — two or more independent groups contain the same normalized value; or
- `independent_values_disagree` — independently sourced values disagree and require attention.

These labels are diagnostics only. They do not themselves change claim state and do not replace the existing verification/trust lifecycle.

## Quality diagnostics

The same `claim_quality_rejection_reason` predicate used by Phase 16 is applied to the persisted corpus. The page shows per-source pass/fail counts, reason totals, attribution-basis counts, and quality-safe active claims that still lack explicit temporal scope.

Historical quality-failed rows remain preserved. The feature does not rewrite or delete them.

## Dashboard

Protected routes:

- `/dashboard/quality-coverage`
- `/dashboard/quality-coverage/status`

They reuse the existing dashboard Basic authentication and response-security middleware. Both routes are read-only.

## Safety boundaries

This milestone does not:

- run source discovery or ingestion;
- change scheduler cadence;
- persist claim-state transitions;
- create verification or trust events;
- enable trust promotion;
- alter PostgreSQL/B2/Qdrant evidence;
- delete, rewrite, or compact historical evidence;
- invent publication/effective dates;
- generate market forecasts or trading signals.

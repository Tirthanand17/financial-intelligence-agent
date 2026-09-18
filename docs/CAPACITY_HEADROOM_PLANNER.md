# Capacity Headroom Planner

## Purpose

The Capacity Headroom Planner turns the project's existing live cloud-capacity measurements into an explicit preservation-first headroom view. It helps the operator see how much measured room remains before the project's configured low-watermark pause threshold and absolute safety ceiling.

It does not change provider plans, quotas, resources, ceilings, scheduler cadence, or stored evidence.

## Routes

- `GET /dashboard/capacity-plan` — protected human-readable planner.
- `GET /dashboard/capacity-plan/status` — protected JSON snapshot.

Both reuse the existing private dashboard authentication, security headers, request IDs, and no-store policy.

## Inputs

The planner reuses the existing dashboard's read-only live measurements:

- Supabase/PostgreSQL measured database bytes;
- Backblaze B2 measured bytes across retained object versions;
- Qdrant measured collection point count.

Those measurements are compared only with the project's explicitly configured ceilings:

- `MONITOR_SUPABASE_MAX_MB`;
- `MONITOR_B2_MAX_MB`;
- `MONITOR_QDRANT_MAX_POINTS`;
- `MONITOR_CAPACITY_LOW_WATERMARK_PERCENT`.

These are project safety ceilings, not assertions about a provider's commercial quota.

## Calculations

For each service with a valid measurement and ceiling, the planner reports:

- measured usage;
- configured project ceiling;
- usage percentage;
- reserved low-watermark percentage;
- pause threshold = ceiling × `(100 - low_watermark_percent)%`;
- remaining units before that pause threshold;
- remaining units before the configured ceiling.

Missing measurements or missing ceilings remain `unknown`. They are never converted into zero or guessed values.

## Forecasting policy

The current project does not persist a validated comparable time series of capacity measurements. Therefore the planner intentionally does **not** estimate days-to-full or days-to-threshold. Its forecast section reports `available=false` with reason `no_persisted_capacity_time_series`.

A later forecasting layer may be added only after comparable measurements are persisted and validated. Until then, inventing a growth rate would weaken the fail-closed policy.

## Preservation policy

When the low-watermark threshold is reached, the project policy remains:

`pause ingestion -> inspect -> expand or migrate capacity -> revalidate -> resume`

The planner explicitly forbids treating any of these as a capacity solution:

- deleting raw evidence;
- truncating provenance/history;
- deleting claim audit events;
- reducing extraction/verification quality;
- silently dropping source coverage.

## Safety

The planner is read-only. It performs no cloud mutation, no evidence deletion, no scheduler change, no trust-state change, no source ingestion, and no provider-plan modification. It introduces no paid infrastructure.

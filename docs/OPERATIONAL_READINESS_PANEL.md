# Operational Readiness Panel

## Purpose

The Operational Readiness panel is a protected, read-only operator view for the live Financial Intelligence Agent. It summarizes the same cloud measurements and persisted monitoring metadata already used by the existing dashboard; it does not introduce a second operational control plane.

## Routes

- `GET /dashboard/readiness` — authenticated human-readable readiness page.
- `GET /dashboard/readiness/status` — authenticated JSON readiness snapshot.

Both routes reuse the dashboard HTTP Basic authentication and security-header middleware. Responses are not cacheable.

## Checks

The panel currently evaluates:

- measured capacity is safe;
- expected and actual Qdrant point counts match;
- unexpected trust events are absent;
- all configured source monitors are ready and have no consecutive failures;
- runtime gates are at the safe defaults (`SOURCE_MONITORING_ENABLED=false`, `SOURCE_AUTO_INGEST_ENABLED=false`, `TRUST_PROMOTION_ENABLED=false` outside bounded scheduled execution);
- the queue has no failed items;
- recent monitor runs contain no failed outcomes;
- Supabase, Backblaze B2 and Qdrant measurements are available.

The panel also shows document/claim counts, queue counts, capacity details, latest successful monitor timestamps and recent monitor runs.

## Read-only boundary

The readiness view cannot:

- ingest or crawl sources;
- modify runtime gates;
- run or modify the scheduler;
- promote or mutate claim state;
- repair Qdrant/PostgreSQL/B2 differences;
- delete or rewrite evidence;
- change storage ceilings.

Failures and mismatches are surfaced for investigation instead of being auto-repaired.

## Integrity scope

This page performs the existing live structural, Qdrant and capacity checks from the operational dashboard. Full evidence-byte/hash verification remains in the production-readiness workflow rather than being executed on every page refresh.

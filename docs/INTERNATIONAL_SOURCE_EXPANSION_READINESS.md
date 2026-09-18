# International Source Expansion Readiness

## Status

Readiness-only post-roadmap milestone. No international source is activated by this work.

Research checkpoint: 2026-09-18.

The existing production source set remains unchanged:

- RBI — `rbi-press-releases-rss`
- SEBI — `sebi-rss`
- NSE — `nse-daily-buyback-rss`
- MoSPI — `mospi-latest-releases-api`

World Bank and IMF are already registered as trusted Authority-B sources for research, but neither is currently in the live monitoring registry.

## Candidate 1 — World Bank Indicators API v2

Candidate ID: `world-bank-indicators-v2`

Official API base:

`https://api.worldbank.org/v2/`

Official documentation:

`https://datahelpdesk.worldbank.org/knowledgebase/articles/889392`

The current source registry already allow-lists `api.worldbank.org`, so no host-policy change is needed merely to design a future adapter.

Activation is still blocked because the project has not yet completed all of the following for this source shape:

- a source-specific World Bank API adapter;
- explicit publication/observation/effective-date mapping rules suitable for this project;
- exact accepted-response byte persistence/reconciliation validation;
- bounded isolated live canary;
- cross-store post-write reconciliation for that canary;
- explicit production scheduler approval after the initial four-source rollout closeout.

No API call is made by the readiness layer.

## Candidate 2 — IMF SDMX API

Candidate ID: `imf-sdmx-v2`

Current official IMF API information describes SDMX 2.1 and SDMX 3.0 access.

Candidate SDMX endpoint:

`https://sdmxcentral.imf.org/sdmx/v2/`

Official IMF API information:

`https://data.imf.org/en/Resource-Pages/IMF-API`

The current IMF source policy allow-lists `www.imf.org` and `imf.org` only. The candidate host `sdmxcentral.imf.org` is therefore intentionally blocked by the current source allow-list.

The host must **not** be added merely to make the readiness check pass. Before any policy change, the operator must validate that the endpoint is the intended official source surface, define the exact adapter/temporal contract, test the downloader/response shape in isolation, and review the host addition as a separate source-policy change.

IMF activation is additionally blocked by the same adapter, temporal-policy, exact-byte reconciliation, bounded-canary, and scheduler-approval requirements as World Bank.

## Required activation sequence

After the current initial scheduler observation period is formally closed, each candidate must progress independently through this sequence:

1. Confirm the official API/documentation surface and source ownership.
2. Define one source-specific adapter; do not use generic unrestricted crawling.
3. Define exactly how source dates map to publication/effective/observation time. Never substitute retrieval time for a missing publication/effective date.
4. Review the source allow-list. Add a new host only through a separate explicit policy change when necessary and justified.
5. Validate bounded discovery/query construction with fixed source-specific limits.
6. Accept one exact response/document payload and preserve the exact accepted bytes.
7. Reconcile its SHA-256, PostgreSQL document/provenance row, B2 object, and expected Qdrant points.
8. Run an isolated bounded canary of at most one evidence item.
9. Run the full fail-closed readiness checks after the canary.
10. Obtain a separate production activation decision before adding the monitor to the recurring scheduler.

A successful candidate check does not automatically activate another candidate.

## Rollout gate

The four-source production scheduler is still in its initial observation period. This milestone therefore deliberately keeps both international candidates out of `app.monitoring.registry.MONITORS`.

No scheduler cadence, processing bound, source order, trust policy, storage policy, or existing monitor definition is changed.

## Safety invariants

This readiness layer:

- performs no candidate network request;
- creates no monitor or discovery row;
- changes no scheduler configuration;
- widens no allow-list;
- performs no ingestion;
- writes no PostgreSQL/B2/Qdrant evidence;
- creates no verification/trust event;
- leaves `TRUST_PROMOTION_ENABLED=false` policy untouched;
- does not delete or rewrite existing evidence;
- introduces no paid infrastructure.

Its purpose is to make blockers explicit before any source expansion is allowed to touch the validated production pipeline.

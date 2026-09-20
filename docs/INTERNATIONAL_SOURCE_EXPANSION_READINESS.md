# International Source Expansion Readiness

## Status

World Bank has passed its bounded exact-byte live evidence canary and is now eligible for a separate production activation decision. It is **not yet** in the live monitoring registry or recurring scheduler.

Research checkpoint: 20 September 2026.

The current production source set remains unchanged:

- RBI — `rbi-press-releases-rss`
- SEBI — `sebi-rss`
- NSE — `nse-daily-buyback-rss`
- MoSPI — `mospi-latest-releases-api`

World Bank and IMF are registered as trusted Authority-B sources for research. IMF remains blocked; World Bank has completed the source-specific adapter, persistence, reconciliation and first live-canary gates but still requires the separate operational-monitor canary and activation milestone.

## Candidate 1 — World Bank Indicators API v2

Candidate ID: `world-bank-indicators-v2`

Official API base:

`https://api.worldbank.org/v2/`

Official documentation:

`https://datahelpdesk.worldbank.org/knowledgebase/articles/889392`

The source registry already allow-lists `api.worldbank.org`.

### Validated bounded contract

`app/sources/world_bank.py` provides the source-specific adapter. The validated initial query contract remains deliberately narrow:

- country fixed to India (`IND`);
- at most 5 recent observations per request;
- only exact reviewed indicators accepted;
- the first operational-monitor contract uses `NY.GDP.MKTP.KD.ZG` — Real GDP Growth;
- arbitrary hosts, paths, query strings, countries and indicator codes are rejected;
- generated URLs are revalidated against the existing World Bank source allow-list;
- redirects are rejected;
- JSON response is capped at 1 MiB.

### Temporal policy

The World Bank response field `date` remains an **observation period** only. It is never rewritten into this project's `publication_date` or `effective_date` fields.

The response-level `lastupdated` field remains source metadata only and is also not a claim publication/effective date.

The adapter accepts annual observation periods (`YYYY`) only. Monthly or quarterly periods require a separately reviewed temporal contract.

Forecast observations explicitly marked `obs_status = F` and missing values are not eligible factual observations.

### Exact-byte persistence and live canary

The production persistence path has been validated end-to-end:

- exact accepted JSON bytes are SHA-256 hashed;
- exact bytes are preserved in private B2;
- the B2 replay hash is checked;
- PostgreSQL stores document/provenance state;
- deterministic World Bank evidence chunks are indexed to Qdrant;
- expected and actual Qdrant point counts must reconcile;
- incomplete reconciliation remains explicitly `reconciliation_required` rather than deleting evidence;
- no structured claims are created under the current annual-observation temporal model.

The bounded live canary executed on 20 September 2026 and passed:

- indicator: `NY.GDP.MKTP.KD.ZG`;
- accepted observation periods: 2025, 2024, 2023;
- evidence chunks: 3;
- structured claims: 0;
- SHA-256 reconciliation: passed;
- PostgreSQL/B2/Qdrant reconciliation: passed;
- post-write production readiness: `FINAL: PASS-READ-ONLY`;
- trust events remained 0.

The initial four-source scheduler rollout also closed cleanly for all required dates from 14–20 September 2026.

### Current World Bank activation gate

World Bank is validation-ready but not production-active. Before adding it to the live monitor registry and scheduler, the project is running a separate source-specific operational-monitor canary.

That operational canary must prove:

- the validated exact-byte World Bank path can execute under the normal monitoring and auto-ingest gates;
- `TRUST_PROMOTION_ENABLED=false` throughout;
- the monitor cadence remains 1440 minutes;
- at most one World Bank evidence document is handled per due cycle;
- successful or unchanged evidence produces normal monitor run/state audit history;
- pre- and post-cycle cloud capacity remain safe;
- zero claims remain the enforced result;
- post-cycle production readiness remains clean.

Only after that succeeds may a separate activation PR add World Bank to the production monitor registry and daily scheduler.

## Candidate 2 — IMF SDMX API

Candidate ID: `imf-sdmx-v2`

Previously considered candidate endpoint:

`https://sdmxcentral.imf.org/sdmx/v2/`

Official IMF API information:

`https://data.imf.org/en/Resource-Pages/IMF-API`

The current IMF source policy allow-lists `www.imf.org` and `imf.org` only. `sdmxcentral.imf.org` remains intentionally blocked.

Do **not** widen the IMF allow-list merely to make readiness pass. Before any IMF policy change, independently verify the current official IMF endpoint and ownership, define the exact source-specific adapter and temporal contract, add bounded offline fixtures/tests, validate exact-byte persistence/reconciliation, run one bounded live canary, and review the source policy separately.

IMF activation therefore remains blocked.

## Activation sequence

Each international candidate progresses independently through:

1. official endpoint/documentation and ownership verification;
2. source-specific bounded adapter;
3. explicit temporal semantics;
4. source allow-list review;
5. bounded query construction;
6. exact response-byte preservation;
7. SHA-256/PostgreSQL/B2/Qdrant reconciliation;
8. one bounded live evidence canary;
9. fail-closed readiness after the canary;
10. source-specific operational-monitor validation where required;
11. separate production activation PR and CI;
12. post-merge scheduler/readiness/deployment verification.

A successful World Bank milestone does not approve IMF.

## Safety invariants

The readiness report itself remains read-only. It:

- performs no candidate network request;
- widens no allow-list;
- creates no production monitor;
- changes no recurring scheduler;
- performs no ingestion;
- mutates no evidence;
- creates no trust event;
- leaves `TRUST_PROMOTION_ENABLED=false` policy untouched;
- deletes or rewrites no historical evidence;
- introduces no paid infrastructure.

World Bank production activation remains explicitly separate from the completed live canary and the current operational-monitor canary.
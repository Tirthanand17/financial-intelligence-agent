# International Source Expansion Readiness

## Status

World Bank has passed both the bounded exact-byte live evidence canary and the source-specific operational-monitor canary. This milestone activates one narrowly bounded World Bank monitor in the recurring production scheduler.

Research checkpoint: 20 September 2026.

The production source set is:

- RBI — `rbi-press-releases-rss`
- SEBI — `sebi-rss`
- NSE — `nse-daily-buyback-rss`
- MoSPI — `mospi-latest-releases-api`
- World Bank — `world-bank-india-gdp-api`

World Bank and IMF remain registered as trusted Authority-B sources. World Bank is production-active under the validated bounded contract below. IMF remains blocked and is not added to the monitor registry or scheduler.

## Candidate 1 — World Bank Indicators API v2

Candidate ID: `world-bank-indicators-v2`

Official API base:

`https://api.worldbank.org/v2/`

Official documentation:

`https://datahelpdesk.worldbank.org/knowledgebase/articles/889392`

The source registry allow-lists `api.worldbank.org`.

### Validated bounded contract

`app/sources/world_bank.py` provides the source-specific adapter. The production query contract remains deliberately narrow:

- country fixed to India (`IND`);
- production indicator fixed to `NY.GDP.MKTP.KD.ZG` — Real GDP Growth;
- production request limited to 3 recent annual observations;
- one evidence document maximum per due cycle;
- monitor cadence fixed at 1440 minutes;
- arbitrary hosts, paths, query strings, countries and unreviewed indicator codes are rejected;
- generated URLs are revalidated against the existing World Bank source allow-list;
- redirects are rejected;
- JSON response is capped at 1 MiB.

### Temporal policy

The World Bank response field `date` remains an **observation period** only. It is never rewritten into this project's `publication_date` or `effective_date` fields.

The response-level `lastupdated` field remains source metadata only and is also not a claim publication/effective date.

The adapter accepts annual observation periods (`YYYY`) only. Monthly or quarterly periods require a separately reviewed temporal contract.

Forecast observations explicitly marked `obs_status = F` and missing values are not eligible factual observations.

### Exact-byte persistence and validation

The persistence path has been validated end-to-end:

- exact accepted JSON bytes are SHA-256 hashed;
- exact bytes are preserved in private B2;
- the B2 replay hash is checked;
- PostgreSQL stores document/provenance state;
- deterministic World Bank evidence chunks are indexed to Qdrant;
- expected and actual Qdrant point counts must reconcile;
- incomplete reconciliation remains explicitly `reconciliation_required` rather than deleting evidence;
- no structured claims are created under the current annual-observation temporal model.

The bounded live evidence canary executed on 20 September 2026 and passed with three 2025/2024/2023 evidence chunks, zero structured claims, clean SHA-256/PostgreSQL/B2/Qdrant reconciliation, zero trust events and post-write `PASS-READ-ONLY` readiness.

The initial four-source scheduler rollout also closed cleanly for all required dates from 14–20 September 2026.

The subsequent World Bank operational-monitor canary also passed its explicit cloud configuration, pre-canary readiness, bounded source-specific cycle validation and post-canary readiness steps. That successful canary is the final evidence gate used by this activation milestone.

### Production activation

World Bank is now represented by the fixed `world-bank-india-gdp-api` monitor and runs after the four existing source cycles in the daily scheduler. Its production path remains source-specific rather than using the generic discovered-document queue.

The recurring cycle preserves:

- `TRUST_PROMOTION_ENABLED=false`;
- the 1440-minute cadence guard;
- at most one World Bank evidence document per due cycle;
- pre- and post-write capacity checks;
- exact-byte B2/PostgreSQL/Qdrant reconciliation;
- zero structured claims under the current temporal contract;
- sequential, non-parallel evidence writes;
- the existing once-daily 09:30 Asia/Kolkata scheduler cadence.

The temporary one-shot operational-canary workflow is removed after its successful use.

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

A successful World Bank activation does not approve IMF.

## Safety invariants

The readiness report itself remains read-only. It performs no candidate network request, widens no allow-list, performs no ingestion, mutates no evidence, creates no trust event, and leaves `TRUST_PROMOTION_ENABLED=false` policy untouched.

Production activation does not delete or rewrite historical evidence, does not increase scheduler frequency, and introduces no paid infrastructure.

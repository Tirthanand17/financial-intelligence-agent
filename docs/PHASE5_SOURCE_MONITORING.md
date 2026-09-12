# Phase 5 Source Monitoring

Phase 5 adds bounded, source-specific monitoring to the existing trusted ingestion pipeline. It is designed to observe explicitly approved feeds and queue new evidence without turning the project into an unrestricted crawler.

## Safety gates

Two independent runtime switches default to `false`:

```text
SOURCE_MONITORING_ENABLED=false
SOURCE_AUTO_INGEST_ENABLED=false
```

`SOURCE_MONITORING_ENABLED` permits a configured monitor to fetch only its explicitly registered feed URL. `SOURCE_AUTO_INGEST_ENABLED` is a second gate required before pending discovered URLs may be passed to the existing trusted ingestion pipeline. Enabling feed observation therefore does not silently enable link following or ingestion.

`TRUST_PROMOTION_ENABLED=false` remains separate and unchanged. Monitoring or ingesting new evidence cannot by itself enable automatic `TRUSTED` promotion.

## Bounded monitoring

A monitor definition contains an explicit source ID, HTTPS feed URL, interval, enabled flag, and maximum new documents per run. The current RBI monitor is configured for its press-release RSS feed.

The monitoring model enforces:

- minimum interval of 60 minutes;
- maximum 100 discovered items per run;
- exponential failure backoff capped at 24 hours;
- source-registry URL validation;
- HTTPS-only discovery URLs;
- bounded RSS/Atom/XML parsing;
- no generic open-web crawling; and
- no automatic financial execution actions.

## Capacity fail-closed policy

Automated work requires capacity signals for Supabase, Backblaze B2, and Qdrant. Provider quotas are never guessed.

If a safe ceiling or current usage measurement is missing, capacity is `UNKNOWN` and automatic work pauses. `LOW` and `EXHAUSTED` capacity also pause processing. The system does not delete evidence, truncate history, reduce source quality, or silently skip trusted records to recover space.

Configured ceilings are optional and default to unset:

```text
MONITOR_SUPABASE_MAX_MB=
MONITOR_B2_MAX_MB=
MONITOR_QDRANT_MAX_POINTS=
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10
```

## Discovery queue

Feed items are persisted in `source_monitor_discoveries` as idempotent queue records. Identity is based on monitor + URL, so a later title/date correction updates the existing item rather than creating duplicate work.

A discovery record tracks:

- source and monitor identity;
- validated URL;
- title and feed publication date when present;
- first/last seen time and seen count;
- pending/ingested/duplicate/rejected state;
- resulting document ID when available; and
- processing attempt count plus symbolic last error code.

Discovery itself never downloads the item URL.

## Gated processing

The discovery processor requires both global switches, an enabled monitor, and safe capacity. It then selects only a bounded number of pending items for that exact monitor/source.

Immediately before ingestion, every queued URL is validated again against the trusted-source registry. A tampered or no-longer-allowed URL becomes `rejected` without a network ingestion call.

Eligible URLs are passed to the existing `ingest_url` pipeline, which retains the established redirect, size, anti-bot/challenge, evidence-quality, provenance, object-storage, vector-indexing, structured-claim, verification, and trust-gate protections.

Operational failures retain the discovery as `pending` and store only symbolic error codes. Raw exception text, request headers, and credentials are not persisted in monitoring telemetry.

## Observability

`source_monitor_states` stores current non-secret operational state. `source_monitor_runs` is append-only run history. `source_monitor_discoveries` is the idempotent discovery queue.

The read-only report:

```bash
python scripts/monitoring_status_report.py
```

shows the two monitoring gates and aggregate monitor/run/discovery counts. It performs no network calls and changes no monitor, ingestion, claim, or trust state.

## Deployment boundary

The Phase 5 code path is implemented and tested, but no scheduled live cloud monitor is enabled by this milestone. Both runtime switches remain `false` in `.env.example`. Before any scheduled deployment, cloud usage must be measured, explicit safe ceilings configured, and a controlled live probe reviewed.

Automatic `TRUSTED` promotion remains disabled independently until the Phase 4 requirement for safely accepted dated primary evidence plus independent corroboration is satisfied.

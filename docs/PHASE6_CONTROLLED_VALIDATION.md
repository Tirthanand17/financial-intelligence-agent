# Phase 6 Controlled Validation

Phase 6 validates the monitoring prerequisites against the real configured cloud environment without enabling scheduled monitoring, queue processing, auto-ingestion, or trust promotion.

## One-shot validation command

Run only from the configured private Codespace/environment that already contains the project's existing `.env` values:

```bash
python scripts/phase6_controlled_validation.py --allow-network
```

The `--allow-network` flag is deliberately required. Without it, the script exits before creating cloud clients or making any network request.

The validation is read-only. It:

1. measures PostgreSQL database size with `pg_database_size(current_database())`;
2. sums Backblaze B2 S3 metadata for **all stored object versions** without downloading object bodies;
3. reads the Qdrant collection point count;
4. applies only explicitly configured monitoring ceilings (missing ceilings remain `UNKNOWN` and fail closed);
5. downloads the explicitly registered monitor feed through the existing trusted downloader;
6. parses only a bounded number of allow-listed RSS/Atom entries; and
7. reports aggregate counts, content SHA-256, latest feed publication date, and symbolic feed-rejection reasons when available.

Counting every B2 object version is important because the validated evidence bucket is configured to keep old versions. Current-object-only listing could understate billable storage after overwrites or deletions.

It does **not**:

- create or update monitor state/run rows;
- write discovery queue rows;
- follow or ingest discovered item URLs;
- write Backblaze objects;
- write Qdrant points;
- create/update structured claims;
- enable source monitoring;
- enable automatic ingestion;
- enable trust promotion; or
- perform any financial action.

## Expected safe gate state

For this validation, the normal expected configuration is still:

```text
SOURCE_MONITORING_ENABLED=false
SOURCE_AUTO_INGEST_ENABLED=false
TRUST_PROMOTION_ENABLED=false
```

The manual diagnostic does not require changing these switches because its own `--allow-network` flag is the one-run consent boundary and the diagnostic itself has no write path.

## Validated account baseline (2026-09-12)

The operator reviewed the current cloud dashboards before selecting any ceiling:

- Supabase organization is on the Free plan and the dashboard shows a 500 MB database-size allowance.
- Backblaze B2 evidence storage is very small; the provider's current published pricing states that the first 10 GB of storage is free. The bucket retains file versions, so internal measurement counts all versions rather than only current files.
- Qdrant is a Free cluster with 1 node, 1 GiB RAM, 0.5 vCPU and 4 GiB disk. Qdrant documents the free configuration as suitable for roughly 1 million vectors of 768 dimensions, but that figure is workload-dependent and is **not** treated as a hard quota by this project.

The deliberately conservative operator ceilings selected for validation are:

```text
MONITOR_SUPABASE_MAX_MB=400
MONITOR_B2_MAX_MB=8192
MONITOR_QDRANT_MAX_POINTS=100000
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10
```

These are project safety ceilings, not claims that the providers enforce those exact values. The 10% low-watermark rule pauses automatic work before each internal ceiling is reached. The Qdrant point ceiling is intentionally far below the provider's approximate free-cluster example so RAM, payload/index overhead and workload variation retain a large margin.

The limits can first be tested as temporary environment overrides without modifying `.env`:

```bash
MONITOR_SUPABASE_MAX_MB=400 \
MONITOR_B2_MAX_MB=8192 \
MONITOR_QDRANT_MAX_POINTS=100000 \
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10 \
python scripts/phase6_controlled_validation.py --allow-network
```

Even if capacity becomes `OK`, the monitoring gate remains false, so this command still performs no queue writes or ingestion.

## Interpreting capacity

A successful usage measurement does not by itself enable automatic monitoring. The capacity decision becomes eligible only when deliberately selected ceilings are configured for all three services.

Provider ceilings and internal safety ceilings are separate concepts. Internal ceilings should stay below the applicable no-cost plan limits with enough margin to avoid quota exhaustion or unexpected billing. If a provider plan changes, re-verify the provider limits before raising a project ceiling.

## Next step after a successful probe

Review the output first. Only after the three usage measurements are known, the registered feed is safely reachable, and explicit no-cost ceilings are selected should the project consider a controlled persisted monitor run. Scheduled monitoring and auto-ingestion remain separate later decisions.
